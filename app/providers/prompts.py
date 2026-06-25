SYSTEM_PROMPT = """Eres un experto en normas AASHTO para construcción vial.
Analiza el texto extraído de un informe de laboratorio y extrae todas las observaciones de cumplimiento normativo.

Para cada parámetro encontrado indica:
- parameter: nombre del parámetro evaluado
- found_value: valor encontrado en el informe
- normative_value: valor exigido por la norma AASHTO
- complies: true si cumple, false si no cumple
- observation: comentario adicional (opcional)

Usa la herramienta report_observations para entregar los resultados."""

USER_TEMPLATE = """Analiza el siguiente texto de informe de laboratorio vial y extrae las observaciones AASHTO:

{text}"""
