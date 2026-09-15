from pydantic import BaseModel
from helpers.utils import get_data_context, contexto_tipo_llamada
from helpers.utils import get_llamada_context
from api.models import FilterModel
from IA.Open_AI import call


class ChatRequest(BaseModel):
    user_message: str
    system_prompt: str | None = None
    llamada_id: int | None = None


async def api_chat_logic(request: ChatRequest, filters: FilterModel):
    try:
        asesor = filters.nombre_asesor or "asesor seleccionado"
        periodo = ""
        if filters.fecha_desde or filters.fecha_hasta:
            periodo = f" Período analizado: {filters.fecha_desde or 'inicio abierto'} a {filters.fecha_hasta or 'fin abierto'}."
        system_prompt = (
            contexto_tipo_llamada(filters) +
            "Eres un asistente experto en call centers para CL Tiene Soluciones en Colombia. "
            "Responde de forma conversacional, clara y en español. "
            f"En este panel estás ayudando a {asesor}.{periodo} "
            "Si preguntan 'quién soy', aclara que no puedes identificar personalmente al usuario "
            "y que el análisis corresponde al asesor seleccionado en el prototipo. "
            "Usa los datos del contexto para responder preguntas específicas. "
            "Para saludos o preguntas generales responde brevemente sin mostrar tablas de datos. "
            "Usa texto plano con saltos de línea, sin HTML ni markdown."
        )
        if request.llamada_id is not None:
            contexto = get_llamada_context(filters, request.llamada_id)
            system_prompt += (
                " Cuando el usuario pregunte por esta llamada, responde solo con base "
                "en su contexto y transcripción. No inventes hechos ni atribuyas frases "
                "que no estén en los datos."
            )
        else:
            contexto = get_data_context(filters.get_query())

        user_message = f"Consulta: {request.user_message}\n\nContexto disponible:\n{contexto}"
        # call() reparte el consumo entre las 2 keys y hace failover si una no tiene cupo.
        contenido, error = call(system_prompt, user_message, temperature=0.7)
        if error:
            return {"respuesta": f"⚠️ {error}"}
        return {"respuesta": contenido}
    except Exception as e:
        return {"respuesta": f"⚠️ Error: {str(e)}"}
