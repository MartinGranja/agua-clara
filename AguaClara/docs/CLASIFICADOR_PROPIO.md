# Clasificador propio (mantenimiento / recuperación / limpieza total)

Segundo método de clasificación, entrenado con las fotos etiquetadas por el dueño. No reemplaza a Gemini: convive con él.

## Cómo decide (dos etapas)
1. Modelo binario: ¿necesita tratamiento? (mantenimiento vs recuperación/limpieza total).
2. Si necesita tratamiento: la pregunta «¿hace más de 4 meses?» decide (más de 4 = limpieza total, menos de 4 = recuperación). Sin respuesta decide el modelo de tres servicios.

## Archivos
- `app/services/own_classifier.py`: rasgos (159, solo numpy + Pillow) y predicción. Lee `app/data/clasificador_propio.json` (28 KB).
- `scripts/entrenar_clasificador.py`: entrena y evalúa (validación cruzada 5×5, regularización elegida con CV anidada; compara regresión logística, SVM y bosque aleatorio). Necesita `pip install scikit-learn` solo para entrenar.
- En la app: `perception.perceive` agrega `meta['propio']` a cada consulta (no cambia el presupuesto ni la confianza). Se apaga con `OWN_CLASSIFIER_ENABLED=false`.

## Comandos
```
python scripts/entrenar_clasificador.py CARPETA --salida resultados_clasificador.json          # solo evaluar
python scripts/entrenar_clasificador.py CARPETA --salida resultados_clasificador.json --guardar # evaluar y guardar el modelo
python scripts/evaluar_fotos.py CARPETA --propio resultados_clasificador.json --salida resultados.json
```
CARPETA tiene las subcarpetas `mantenimiento`, `recuperacion` y `limpieza total`. Reentrenar al sumar fotos nuevas.

## Resultado actual (90 fotos, VC 5×5)
Regresión logística (desplegada): exactitud 0,78 en 3 servicios y 0,85 en mantenimiento vs tratamiento. SVM 0,81/0,87. Bosque aleatorio 0,83/0,88. Con la pregunta (cota superior): 0,85.
Preliminar: una sola cámara, se asume una pileta distinta por foto y la clase recuperación tiene solo 19 fotos.
