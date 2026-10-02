"""Servidor de Médula: /acquire, /notify, /release. Responde en el formato de salida de los hooks."""
from __future__ import annotations

import threading
import time
from dataclasses import asdict

from fastapi import FastAPI, Header, HTTPException, Request

from . import camino_lento, intencion, plan, simbolos
from .almacen import Almacen
from .config import Config
from .decisores import ErrorDecisor, cliente, construir
from .decisores.jev import Jev
from .intencion import Accion


def _permitir(avisos: list[str]) -> dict:
    salida = {"hookEventName": "PreToolUse", "permissionDecision": "allow"}
    if avisos:
        salida["additionalContext"] = "\n\n".join(avisos)
    return {"hookSpecificOutput": salida}


def _denegar(motivo: str, avisos: list[str]) -> dict:
    texto = motivo + ("\n\n" + "\n\n".join(avisos) if avisos else "")
    return {"hookSpecificOutput": {"hookEventName": "PreToolUse", "permissionDecision": "deny",
                                   "permissionDecisionReason": texto}}


class Nucleo:
    def __init__(self, config: Config):
        self.config = config
        self.db = Almacen(config.db)
        self.or_ = cliente(config)
        self.decisor = construir(config, self.or_)
        self.jev = next((d for d in self.decisor.decisores if isinstance(d, Jev)), None)
        self.cond = threading.Condition()
        self.hilos: list[threading.Thread] = []
        self.ajustes: dict[str, float] = {}  # prioridad ajustada por el camino lento (reordenar)
        # Acción vista en el acquire, por tool_use_id: en el notify el fichero ya está escrito y el diff saldría vacío.
        self.acciones: dict[str, Accion] = {}

    # --- utilidades -----------------------------------------------------------

    def asegurar(self, agente: str, tarea: str | None, session_id: str | None = None) -> dict:
        if not agente:
            raise HTTPException(400, "falta la cabecera X-Medula-Agente")
        self.db.registrar(agente, tarea or None, session_id)
        return self.db.agente(agente)

    def _tarea(self, agente: str) -> str:
        a = self.db.agente(agente) or {}
        return a.get("tarea") or ""

    def _resumen_tarea(self, agente: str) -> str:
        return intencion.resumen_tarea(self.config.tareas_dir, self._tarea(agente))

    def _otros(self, agente: str) -> list[dict]:
        salida = []
        for o in self.db.activos(excepto=agente):
            locks = self.db.locks(o["id"])
            salida.append({
                "agente": o["id"],
                "tarea": intencion.resumen_tarea(self.config.tareas_dir, o.get("tarea")),
                "tiene": sorted({lk["recurso"] for lk in locks}),
                "intencion": intencion.resumen_intenciones(locks) or "(aún no ha escrito nada)",
            })
        return salida

    def _prioridad(self, agente: str) -> float:
        return plan.prioridad(self.config.plan, self._tarea(agente), self.ajustes.get(agente, 0.0))

    def _registrar(self, tipo: str, agente: str, accion: Accion | None, lote=None, **kw) -> None:
        datos = dict(tipo=tipo, agente=agente, accion=accion.para_estado() if accion else None, **kw)
        if lote is not None:
            datos.update(
                pregunta=lote.pregunta, latencia_ms=lote.latencia_ms, coste_usd=lote.coste_usd,
                decisor=lote.decisor, modelo=lote.modelo, reserva_de=",".join(lote.reserva_de) or None,
                respuesta={"veredictos": {x: asdict(v) for x, v in lote.veredictos.items()}, "crudo": lote.crudo},
            )
        self.db.registrar_decision(**datos)

    # --- decisión -------------------------------------------------------------

    def _decidir(self, agente: str, accion: Accion) -> tuple[str, str | None, str]:
        """Devuelve (veredicto, esperar_a, motivo) con veredicto en conceder | esperar | reescribir."""
        otros = self._otros(agente)
        if not otros:
            self._registrar("acquire", agente, accion, decisor="regla", veredicto="conceder", p_choca=0.0,
                            latencia_ms=0.0, coste_usd=0.0, pregunta="sin otros agentes activos")
            return "conceder", None, ""
        est = intencion.estado(agente, self._resumen_tarea(agente), accion, otros)
        ids = [o["agente"] for o in otros]
        veredictos, lotes = {}, []
        # Experimento 1: regla de símbolos compartidos (sin modelo); Jev solo decide la compatibilidad.
        regla = {}
        if self.config.regla_simbolos and self.jev:
            regla = {o["agente"]: s for o in otros if (s := simbolos.compartidos(accion.para_estado(), o))}
            if regla:
                self.db.registrar_decision(tipo="regla", agente=agente, accion=accion.para_estado(),
                                           pregunta="simbolos_compartidos", decisor="regla_simbolos",
                                           veredicto="probable:" + ",".join(sorted(regla)), latencia_ms=0.0,
                                           coste_usd=0.0, respuesta={x: sorted(s) for x, s in regla.items()})
                try:
                    lote_c = self.jev.compatible(est, regla)
                    veredictos.update(lote_c.veredictos)
                    lotes.append(lote_c)
                except ErrorDecisor as e:  # sin respuesta de Jev: esos agentes van por el camino normal
                    self.db.registrar_decision(tipo="acquire", agente=agente, accion=accion.para_estado(),
                                               pregunta="compatible", decisor="regla+jev", error=str(e))
                    regla = {}
        resto = [x for x in ids if x not in regla]
        if resto:
            lote = self.decisor.acquire(est, resto)
            veredictos.update(lote.veredictos)
            lotes.append(lote)
        lote = lotes[-1]
        x, v = max(veredictos.items(), key=lambda kv: kv[1].p)
        cfg = self.config
        if v.p < cfg.umbral_bajo:
            veredicto, esperar_a, motivo = "conceder", None, ""
        elif v.p > cfg.umbral_alto and v.remedio != "replanificar":
            veredicto, esperar_a, motivo = "esperar", x, self._motivo_espera(accion, x, v.p, lote.decisor, v.motivo)
        elif not cfg.semantico:
            veredicto, esperar_a, motivo = "esperar", x, self._motivo_espera(accion, x, v.p, lote.decisor, v.motivo)
        else:
            veredicto = "lento"
        for lt in lotes:
            pmax = max(w.p for w in lt.veredictos.values())
            self._registrar("acquire", agente, accion, lt, estado_enviado=est, veredicto=veredicto, p_choca=pmax,
                            confianza=max(pmax, 1 - pmax), error=" | ".join(self.decisor.ultimos_errores) or None)
        if veredicto != "lento":
            return veredicto, esperar_a, motivo

        criterios = {f"{agente} ({self._tarea(agente)})": intencion.criterios_tarea(cfg.tareas_dir, self._tarea(agente))}
        for o in self.db.activos(excepto=agente):
            criterios[f"{o['id']} ({o.get('tarea')})"] = intencion.criterios_tarea(cfg.tareas_dir, o.get("tarea"))
        s = camino_lento.resolver(self.or_, cfg, est, {k: round(w.p, 3) for k, w in veredictos.items()}, x, criterios)
        for paso in s.pasos:
            resp = paso.get("respuesta") or {}
            if paso.get("verificacion"):
                ver = "verificacion:" + ("incumple" if resp.get("incumple") is not False else "ok")
            else:
                ver = resp.get("salida") if not paso.get("rechazo") else f"rechazada:{resp.get('salida')}"
            self.db.registrar_decision(
                tipo="lento", agente=agente, accion=accion.para_estado(),
                pregunta="verificacion" if paso.get("verificacion") else "salida", estado_enviado=est,
                respuesta=paso.get("respuesta"), veredicto=ver, latencia_ms=paso.get("latencia_ms"),
                coste_usd=paso.get("coste_usd"), decisor=paso["decisor"], modelo=paso["modelo"],
                error=paso.get("error") or paso.get("rechazo"), finish_reason=paso.get("finish_reason"))
        if s.salida == "conceder":
            return "conceder", None, ""
        if s.salida == "reescribir":
            return "reescribir", None, f"Médula: {s.instrucciones or s.motivo}"
        if s.salida == "reordenar":
            if s.primero == agente:
                self.ajustes[agente] = self.ajustes.get(agente, 0.0) - 1
                return "conceder", None, ""
            x = s.primero or x
        else:
            x = s.esperar_a or x
        return "esperar", x, self._motivo_espera(accion, x, None, "camino lento (" + (s.pasos[-1]["decisor"] if s.pasos else "") + ")", s.motivo)

    def _motivo_espera(self, accion: Accion, x: str, p: float | None, decisor: str, detalle: str | None) -> str:
        otro = self.db.agente(x) or {}
        recursos = sorted({lk["recurso"] for lk in self.db.locks(x)})
        tarea = intencion.resumen_tarea(self.config.tareas_dir, otro.get("tarea")).split(". ")[0]
        return (
            f"Médula: {x} está trabajando en «{tarea}»"
            + (f" y tiene {', '.join(recursos)}" if recursos else "")
            + f". Tu acción ({accion.resumen()}) choca con ese trabajo ("
            + (f"probabilidad {p:.2f}, " if p is not None else "") + f"decisor {decisor})"
            + (f": {detalle}" if detalle else "")
            + f". Espera a que {x} termine: reinténtalo más tarde (por ejemplo, tras `sleep 60`) o avanza en otra "
              "parte de tu tarea que no dependa de esto. No termines la sesión sin completar tu tarea."
        )

    # --- endpoints ------------------------------------------------------------

    def acquire(self, agente: str, tarea: str | None, cuerpo: dict) -> dict:
        self.asegurar(agente, tarea, cuerpo.get("session_id"))
        self.db.liberar_transitorios(agente)  # su acción anterior ya terminó, aunque no llegase el PostToolUse
        accion = intencion.accion_de(cuerpo.get("tool_name", ""), cuerpo.get("tool_input") or {}, self.config.raiz)
        if cuerpo.get("tool_use_id"):
            self.acciones[cuerpo["tool_use_id"]] = accion
        avisos = self.db.recoger_buzon(agente)
        if not accion.escritura:
            self._registrar("acquire", agente, accion, decisor="regla", veredicto="conceder", p_choca=0.0,
                            latencia_ms=0.0, coste_usd=0.0, pregunta="lectura")
            return _permitir(avisos)

        limite = time.monotonic() + self.config.espera_max
        id_cola, motivo = None, ""
        while True:
            veredicto, esperar_a, motivo_nuevo = self._turno(agente, accion, id_cola, limite)
            motivo = motivo_nuevo or motivo
            if veredicto == "conceder":
                tarea_ = self._tarea(agente)
                self.db.anadir_lock(agente, accion.recurso, intencion.intencion_de_lock(tarea_, accion),
                                    transitorio=accion.recurso == "repo")
                self.db.set_estado(agente, "trabajando")
                self.db.set_ultima_accion(agente, accion.resumen())
                if id_cola:
                    self.db.cerrar_cola(id_cola, "concedido")
                self._despertar()
                return _permitir(avisos)
            if veredicto == "reescribir":
                if id_cola:
                    self.db.cerrar_cola(id_cola, "denegado")
                self.db.set_estado(agente, "trabajando")
                self._despertar()
                return _denegar(motivo, avisos)
            # esperar. Si el otro me está esperando a mí, pasa el de mejor prioridad (sin bloqueo mutuo).
            otro = self.db.agente(esperar_a) or {}
            if otro.get("estado") == "esperando" and otro.get("espera_a") == agente \
                    and self._prioridad(agente) <= self._prioridad(esperar_a):
                self.db.registrar_decision(tipo="acquire", agente=agente, accion=accion.para_estado(),
                                           pregunta="espera cruzada", decisor="regla", veredicto="conceder",
                                           latencia_ms=0.0, coste_usd=0.0)
                tarea_ = self._tarea(agente)
                self.db.anadir_lock(agente, accion.recurso, intencion.intencion_de_lock(tarea_, accion),
                                    transitorio=accion.recurso == "repo")
                self.db.set_estado(agente, "trabajando")
                if id_cola:
                    self.db.cerrar_cola(id_cola, "concedido")
                self._despertar()
                return _permitir(avisos)
            if id_cola is None:
                id_cola = self.db.encolar(agente, accion.recurso, accion.para_estado(), esperar_a, self._prioridad(agente))
            else:
                self.db.actualizar_espera(id_cola, esperar_a)
            self.db.set_estado(agente, "esperando", esperar_a)
            if not self._esperar_fin(esperar_a, limite):
                self.db.cerrar_cola(id_cola, "caducado")
                self.db.set_estado(agente, "trabajando")
                self._despertar()
                return _denegar(motivo, avisos)
            # El agente al que esperaba ha terminado: se vuelve a decidir con el estado nuevo.

    def _turno(self, agente, accion, id_cola, limite):
        """Si varios esperaban al mismo agente, vuelven a decidir por orden de prioridad."""
        if id_cola is not None:
            with self.cond:
                while time.monotonic() < limite:
                    fila = self.db.cola_de(id_cola)
                    rivales = [c for c in self.db.cola() if c["espera_a"] == fila["espera_a"] and c["id"] != id_cola
                               and (c["prioridad"], c["desde"]) < (fila["prioridad"], fila["desde"])]
                    if not rivales:
                        break
                    self.cond.wait(timeout=0.2)
        return self._decidir(agente, accion)

    def _esperar_fin(self, x: str, limite: float) -> bool:
        with self.cond:
            while True:
                otro = self.db.agente(x)
                if not otro or otro["estado"] == "terminado":
                    return True
                restante = limite - time.monotonic()
                if restante <= 0:
                    return False
                self.cond.wait(timeout=min(restante, 1.0))

    def _despertar(self) -> None:
        with self.cond:
            self.cond.notify_all()

    def notify(self, agente: str, tarea: str | None, cuerpo: dict, sincrono: bool = False) -> dict:
        self.asegurar(agente, tarea, cuerpo.get("session_id"))
        accion = self.acciones.pop(cuerpo.get("tool_use_id") or "", None) or \
            intencion.accion_de(cuerpo.get("tool_name", ""), cuerpo.get("tool_input") or {}, self.config.raiz)
        if accion.escritura:
            self.db.set_ultima_accion(agente, accion.resumen())
            self.db.liberar_transitorios(agente)
            self._despertar()
            if self.config.semantico and self.db.activos(excepto=agente):
                hilo = threading.Thread(target=self._interrumpir, args=(agente, accion), daemon=True)
                self.hilos.append(hilo)
                hilo.start()
                if sincrono:
                    hilo.join()
        avisos = self.db.recoger_buzon(agente)
        if not avisos:
            return {}
        return {"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": "\n\n".join(avisos)}}

    def _interrumpir(self, agente: str, accion: Accion) -> None:
        """¿Invalida este cambio el plan de cada otro agente activo? Una sola petición."""
        otros = self._otros(agente)
        if not otros:
            return
        est = intencion.estado(agente, self._resumen_tarea(agente), accion, otros)
        try:
            lote = self.decisor.invalida(est, [o["agente"] for o in otros])
        except ErrorDecisor as e:
            self._registrar("notify", agente, accion, pregunta="invalida", estado_enviado=est, error=str(e))
            return
        pmax = max((v.p for v in lote.veredictos.values()), default=0.0)
        enviados = [x for x, v in lote.veredictos.items() if v.p > self.config.umbral_aviso]
        self._registrar("notify", agente, accion, lote, estado_enviado=est, p_choca=pmax,
                        veredicto=f"avisar:{','.join(enviados)}" if enviados else "sin_avisos",
                        error=" | ".join(self.decisor.ultimos_errores) or None)
        for x in enviados:
            v = lote.veredictos[x]
            texto = (f"Médula: aviso de {agente}. Acaba de hacer {accion.resumen()}"
                     f" ({(accion.cambio or '')[:300]}). Puede afectar a tu plan"
                     + (f": {v.motivo}" if v.motivo else "") + ". Revisa si tienes que adaptar lo que estás haciendo.")
            self.db.al_buzon(x, texto, de=agente, p_invalida=v.p)

    def release(self, agente: str) -> dict:
        if not agente or not self.db.agente(agente):
            return {}
        self.db.terminar(agente)
        for c in self.db.cola(solo_esperando=False):
            if c["espera_a"] == agente and c["estado"] == "caducado":
                self.db.al_buzon(c["agente"], f"Médula: {agente} ha terminado. Ya puedes reintentar lo que estaba "
                                              f"esperando ({c['recurso']}); revisa antes sus cambios.", de="medula")
                self.db.cerrar_cola(c["id"], "avisado")
        self._despertar()
        return {}


def crear_app(config: Config) -> FastAPI:
    nucleo = Nucleo(config)
    app = FastAPI(title="Médula")
    app.state.nucleo = nucleo

    @app.post("/registrar")
    def registrar(cuerpo: dict):
        nucleo.asegurar(cuerpo.get("agente", ""), cuerpo.get("tarea"))
        return {"ok": True}

    @app.post("/acquire")
    def acquire(req_cuerpo: dict, x_medula_agente: str = Header(default=""), x_medula_tarea: str = Header(default="")):
        return nucleo.acquire(x_medula_agente, x_medula_tarea, req_cuerpo)

    @app.post("/notify")
    def notify(req_cuerpo: dict, x_medula_agente: str = Header(default=""), x_medula_tarea: str = Header(default="")):
        return nucleo.notify(x_medula_agente, x_medula_tarea, req_cuerpo)

    @app.post("/release")
    def release(req_cuerpo: dict, x_medula_agente: str = Header(default="")):
        return nucleo.release(x_medula_agente or req_cuerpo.get("agente", ""))

    @app.get("/estado")
    def estado():
        db = nucleo.db
        return {"agentes": db.agentes(), "locks": db.locks(), "cola": db.cola(), "buzon": db.buzon(),
                "decisiones": db.decisiones(20)}

    return app
