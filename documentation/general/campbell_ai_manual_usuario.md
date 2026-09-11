# Campbell AI — manual de uso

Guía para quien consulta el asistente desde el dashboard. Explica qué responde, cómo pedirlo con
precisión y qué limitaciones tiene hoy.

Escrito como parte de la certificación funcional (observación C05 de `plan.md`). El diagnóstico
técnico que lo respalda está en la última sección.

---

## 1. Los tres niveles del análisis de aceite

Casi todas las confusiones vienen de mezclar estos tres niveles. Responden preguntas distintas y
ninguno sustituye a otro.

| Nivel | Qué es | Qué te dice |
| --- | --- | --- |
| **Equipo** | Una unidad completa | Su **estado agregado**, calculado ponderando sus componentes. No es el resultado de una muestra. |
| **Componente** | Una posición física: motor, transmisión, mando final | Su condición, tomada de la muestra seleccionada para él. |
| **Muestra** | Una extracción de aceite de un componente en una fecha, con su `sampleNumber` | Los ensayos de esa extracción y cuáles quedaron fuera de límite. |

Consecuencia práctica: un equipo puede estar **Anormal** mientras su motor está **Normal**, porque
lo que lo llevó a Anormal fue otro componente. Si el asistente te da un estado de equipo, te dirá
qué componentes lo componen y con qué peso; si te da una muestra, te dirá su fecha y su número.

**Cómo preguntar bien:** nombra el nivel que te interesa.

- “¿Cómo está la flota por aceite?” → nivel equipo.
- “¿Qué componentes están anormales en TDZ006?” → nivel componente.
- “¿Qué ensayos se salieron de límite en la última muestra del motor de TDZ006?” → nivel muestra.

---

## 2. Condición actual frente a historial

Por defecto, la condición de un componente es **su muestra más reciente disponible, sin ventana de
tiempo**. Si esa muestra tiene ocho meses, se te entrega igual y se te informa la fecha: es lo
último que se sabe de ese componente.

| Quieres… | Pídelo así |
| --- | --- |
| La condición de hoy | “¿Cómo está el motor de TDZ006?” |
| La evolución | “Muéstrame la evolución del hierro del motor de TDZ006 en el último año.” |
| Un período concreto | “¿Qué muestras del motor de TDZ006 hay entre marzo y junio de 2026?” |
| La última dentro de un período | “¿Cuál fue la última muestra del motor de TDZ006 antes de junio de 2026?” |

“La última muestra dentro de un período” y “el historial del período” son cosas distintas y el
asistente las distingue. Si pides una y necesitas la otra, dilo explícitamente.

Son tres alcances, y tanto el texto como los gráficos usan los mismos:

| Alcance | Qué te devuelve |
| --- | --- |
| Condición actual | La muestra más reciente de cada componente, sin ventana de tiempo. |
| Última dentro del período | La última muestra de cada componente dentro del período que pediste. |
| Historial | Todas las muestras del período. |

Cada respuesta declara cuál usó, y los gráficos lo dicen en su subtítulo. Si pides una ventana
(“los últimos 30 días”), estás pidiendo un período: los componentes muestreados hace más tiempo
quedan fuera. Para la condición de hoy, no acotes el tiempo.

**Ojo con esto:** si preguntas “¿qué componentes están anormales?”, la respuesta mira la condición
**actual** de cada componente. Una muestra antigua que fue anormal, pero que ya fue superada por
una muestra normal más reciente, no aparece — y eso es correcto. Para verla, pide el historial.

---

## 3. Límites de referencia

Cuando el asistente dice que un ensayo está fuera de límite, puedes pedirle contra qué lo comparó:

> “¿Contra qué límites se comparó la última muestra del motor de TDZ006?”

Te devuelve los cuatro límites del contrato vigente y, para cada ensayo, **cómo se obtuvo** esa
referencia:

La consulta muestra la **calibración vigente**. Su versión no demuestra qué calibración se usó
al emitir un informe histórico; cuando esa aplicación no está verificada, el asistente lo indica.

- calibrada para el rango de horas de esa muestra;
- calibrada para todos los rangos;
- **aproximada** — promedio entre rangos, porque no hay límite calibrado para el rango de esa
  muestra. El asistente te lo dirá explícitamente y te indicará de qué rangos salió el promedio.
  Una banda promediada **no tiene una fecha de cálculo propia**: si se derivó de calibraciones de
  fechas distintas, se te dicen todas en vez de citar una sola;
- sin calibración: no hay límite para ese ensayo y componente. Sin referencia, el asistente **no
  afirmará** que un valor está alto o bajo.

Una diferencia de escritura en el nombre del componente (espacios de más, mayúsculas) ya no se
confunde con falta de calibración. Si la fuente de límites tiene dos entradas que solo difieren en
eso y sus referencias son contradictorias, se reporta una ambigüedad de la fuente. Si las
referencias son idénticas, se utiliza una y se advierte que hay un duplicado que debe corregirse.

Los cuatro límites son LIC (inferior condenatorio), LIM (inferior marginal), LSM (superior
marginal) y LSC (superior condenatorio). Un límite inferior ausente significa ausente, nunca cero:
muchos metales de desgaste no tienen límite inferior y un valor bajo en ellos es simplemente
normal.

---

## 4. Modelo predictivo

El `ranking` predictivo es un **orden de prioridad**, no una probabilidad de falla. Un ranking de
62 no significa “62 % de probabilidad de fallar”.

Al explicar un riesgo, el asistente separa tres cosas:

1. **Las variables que el modo de falla considera.** Es una asociación documentada, y cambia según
   la empresa y el componente. Para CDA, por ejemplo, la degradación de aceite considera viscosidad
   y hollín; el hierro pertenece al desgaste abrasivo.
2. **Las lecturas observadas**, con su fecha. En aceite es un valor medido; en telemetría es una
   *tasa de tiempo sobre el límite* en un estado de máquina, no una lectura instantánea.
3. **La contribución de cada variable al puntaje**, que el modelo **no publica**. Por eso el
   asistente no te dirá que una variable causa el riesgo.

Si te interesa saber si una lectura de aceite está realmente alta, pide sus límites (sección 3).

---

## 5. Tiempos de laboratorio

Las preguntas del tipo “¿cuánto demora el laboratorio?” se responden con la misma fórmula y la
misma población que **Monitoreo > Aceite > Laboratorio**, así que los números coinciden con esa
pantalla.

- **Tránsito**: de la toma de muestra a la recepción en laboratorio.
- **Laboratorio**: de la recepción al informe.
- **Diagnóstico**: de la toma de muestra al informe.

Cada duración se cuenta en **días enteros** (una muestra que tardó 2 días cuenta 2), pero el
**promedio de esas duraciones sí lleva decimales**: “2,3 días” es un promedio, no una medición
individual. Cada promedio trae además su propio denominador. Cuatro cosas que conviene saber leer:

- El período por defecto son **seis meses hasta el informe más reciente disponible**, y el
  asistente te lo declara. Si quieres otro, pídelo: “…entre enero y marzo de 2026”.
- Si una fecha falta, el promedio se calcula solo sobre las muestras que la tienen. **Un dato
  faltante no es un cero.**
- Si la fuente no distingue recepción de informe, se reporta el tiempo de diagnóstico y se te dice
  que el desglose no está disponible. Tampoco es cero.
- **La población se puede cuadrar.** La respuesta trae cuántas filas tenía la fuente, cuántas se
  excluyeron por no tener fecha de extracción, cuántas quedaron sin fecha de informe y cuántas
  entraron al período. Si el total te parece bajo, esos números explican la diferencia; una fila
  excluida no es una demora de cero.

No pidas porcentaje de cumplimiento ni SLA: no hay fórmula ni umbral contractual acordados, y el
asistente no los inventará. El umbral que aparece en el gráfico del dashboard es una referencia de
configuración.

---

## 6. Preguntas sugeridas

Los botones de preguntas sugeridas dependen de dos cosas de **tu** empresa: los módulos que tiene
habilitados y las fuentes que realmente están disponibles. Una empresa con solo aceite ve preguntas
de aceite y de laboratorio; una con alertas y telemetría ve las suyas. Si un módulo está
desactivado —o si un archivo de datos no llegó— su pregunta desaparece, aunque el resto siga
disponible. Al cambiar de empresa las sugerencias se recalculan y no se arrastran las anteriores.

También se revisan cada cinco minutos y ante fallos. Al pulsar una sugerencia se comprueba de
nuevo su disponibilidad, para evitar enviar una pregunta cuya fuente dejó de estar utilizable.

Si no aparece ninguna sugerencia, esa empresa no tiene fuentes habilitadas que puedan responderlas.
Puedes preguntar directamente y el asistente te dirá qué análisis están disponibles.

---

## 7. Nueva conversación

**Nueva conversación** abre un hilo aparte. **No borra el anterior**: queda en el panel de
historial y puedes volver a abrirlo mientras el respaldo esté habilitado.

Úsala cuando cambies de tema. Es lo correcto, además, para evitar el problema de la sección
siguiente: un hilo largo sobre varios equipos hace más probable que una referencia ambigua se
resuelva mal.

---

## 8. Limitación conocida: referencias entre turnos

**Qué pasa.** En una conversación de varios turnos, una pregunta que se apoya en un pronombre o en
una referencia implícita puede resolverse mal. Ejemplo:

1. “¿La última muestra del motor de TDZ006?” → responde bien.
2. “¿Qué ensayos explican ese estado?” → puede perder el equipo o el componente.
3. “¿Y la transmisión del mismo equipo?” → puede perder el equipo.

**Por qué.** Dos mecanismos independientes, ambos verificables leyendo el código. Explican cómo
puede ocurrir. La evaluación del 11 de septiembre de 2026 comprobó una secuencia de tres turnos
sobre muestra, ensayos y fecha para CDA y ENEX. Esa evidencia acotada **no** mide la frecuencia
general del problema ni todas las combinaciones de referencias:

- Los agentes especializados que consultan los datos **no ven la conversación**. Reciben solo el
  texto que el agente coordinador les pasa. Si ese texto conserva el pronombre en lugar de
  reescribir la entidad, no hay forma de resolverlo
  (`src/campbell_ai/agents_runtime.py`, `data_analysis` / `visualization_analysis` /
  `technical_analysis`: la entrada es únicamente `question` + `context`).
- El historial replicado tiene un presupuesto de mensajes y de caracteres
  (`_budgeted_history`, con `max_history_messages`, `max_history_message_chars` y
  `max_history_chars` en `src/campbell_ai/config.py`). Se conserva lo más reciente; una entidad
  nombrada solo en el primer turno puede quedar fuera si las respuestas intermedias son largas —
  una tabla de datos ocupa varios miles de caracteres. El recorte se marca en el texto, pero la
  entidad ya no está.

Esto **no** es falta de memoria: el historial existe y se replica en cada turno.

**Mitigación aplicada.** El prompt del agente coordinador ahora le exige reescribir las entidades
resueltas (equipo, componente, período, identificador, alcance) antes de delegar, y preguntar en
una línea cuando la referencia sea genuinamente ambigua o cuando la entidad ya no esté en el
historial replicado.

Es una instrucción al modelo, no una garantía del sistema: las secuencias evaluadas conservaron
las entidades, pero conversaciones largas o ambiguas requieren más cobertura. Si ves una respuesta que se refiere a
otro equipo o componente, repregunta con los nombres completos.

**Qué puedes hacer tú, mientras tanto.**

- Nombra el equipo y el componente en cada pregunta que dependa de ellos. Es lo que más reduce el
  riesgo, porque elimina la referencia ambigua en origen. No está medido con qué frecuencia el
  asistente resuelve bien una referencia implícita.
- Al cambiar de componente, repite el equipo: “¿y la transmisión de TDZ006?” en vez de “¿y la
  transmisión?”.
- Al cambiar de tema, abre una **nueva conversación**.
- Si una respuesta parece referirse a otro equipo o componente, repregúntalo con los nombres
  completos. El asistente declara en cada respuesta la fecha y el alcance que usó: úsalos para
  verificar que respondió sobre lo que preguntaste.

**Pendiente.** La solución estructural es arrastrar las entidades resueltas como contexto
explícito y pequeño, que sobreviva al recorte del historial y viaje a los especialistas. Queda en
backlog; no forma parte de esta entrega.

---

## 9. Qué el asistente no hará

Por diseño, y conviene saberlo para no interpretarlo como una falla:

- No inventa unidades de medida. Las fuentes no publican la unidad de una señal. La única
  excepción son los tiempos de laboratorio, que son días porque se calculan restando fechas.
- No entrega cifras sin respaldo en los datos. “No disponible en la fuente” es una respuesta
  válida.
- No presenta ausencia de datos como condición normal ni como cero.
- No afirma causalidad a partir del modelo predictivo.
- No promete análisis que tu empresa no puede ejecutar: te dirá cuál falta y por qué.
