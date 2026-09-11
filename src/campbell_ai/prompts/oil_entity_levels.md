## Niveles de aceite: equipo, componente y muestra

Un solo glosario para todos los agentes. Estos tres niveles responden preguntas distintas y
ninguno sustituye a otro. Confundirlos es el error que hay que evitar: atribuir a un componente el
estado agregado del equipo, o presentar el agregado como si fuera el resultado de una muestra.

- **Equipo.** Una unidad. Su estado global es un **agregado** calculado aguas arriba ponderando sus
  componentes. Lo entrega `query_oil_status` (`level: "equipo"`), junto con
  `contributing_components` y su ponderación cuando la fuente los publica. No es el resultado de
  ninguna muestra y no se recalcula aquí.
- **Componente.** Una posición física del equipo: motor, transmisión, mando final. Su condición
  proviene de la muestra seleccionada para ese componente.
- **Muestra.** Una extracción de aceite de un componente en una fecha, identificada por
  `sampleNumber`. Sus ensayos viajan juntos en esa fila. Lo entrega `query_oil_components`
  (`level: "componente"`).

### Reglas de selección

1. Sin período ni historial pedidos explícitamente, la condición actual de un componente es **su
   muestra más reciente disponible**, sin ventana temporal. Si tiene más de 60 días se entrega
   igual y se informa la fecha; no la descartes ni la reemplaces por la muestra de otro
   componente.
2. La muestra se elige **antes** de filtrar condición, severidad o anomalía. Filtrar primero
   rescata una muestra antigua anormal y esconde la reciente normal.
3. Si preguntan por una muestra sin nombrar el componente y hay varios candidatos, muestra sus
   últimas muestras claramente separadas o pide una precisión breve. No elijas uno por gravedad
   sin decirlo.
4. Declara siempre el alcance que usaste y la fecha de la muestra. `scope_detail` del resultado ya
   trae el nivel, el criterio de selección y el campo de fecha aplicado.
5. Explica por separado el resultado de la muestra, la condición del componente y el estado del
   equipo. Al explicar un estado de equipo, atribúyelo solo a los componentes que la fuente
   respalda en `contributing_components`.
6. Falta de datos no es condición normal. Si un componente o equipo no tiene muestras, dilo como
   ausencia de datos y no lo sustituyas por otra fuente ni por otro componente.
7. Si falta el identificador de muestra o la fórmula de ponderación, declara la limitación; no los
   inventes.
