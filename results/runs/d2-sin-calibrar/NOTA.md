# d2-sin-calibrar (antes d2): fuera de la matriz

Modo D lanzado con los umbrales iniciales 0,2 / 0,8 (sin --umbral-bajo/--umbral-alto) y antes de que el
camino lento recibiera los criterios de aceptación. No es comparable con d2-d4 de la matriz de E-07, que
usan 0,25 / 0,50 y el filtro de la spec. Resultado: 37/37 en verde; Médula detectó T1-T2 por espera
(T2 esperó 120 s a T1) pero no T3-T4; T3 esperó 177 s a T2 (bloqueo innecesario).
