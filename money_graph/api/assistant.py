"""HTTP adapter for the existing assistant from upstream commit ab08d0d."""
import asyncio
from typing import Literal
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, ConfigDict, Field
import pandas as pd
from mg.assistant import GraphTools, AssistantUnavailable, ask_openai, settings
from mg.provider_errors import provider_error_details
from . import storage

class AssistantQuery(BaseModel):
    model_config = ConfigDict(extra='forbid')
    gids: list[str] = Field(min_length=1, max_length=5)
    mode: Literal['explain','common_recipients','paths','missing_data','question'] = 'explain'
    question: str = Field(default='', max_length=1000)
    allow_external: bool = False

def router(loaded):
    routes = APIRouter(tags=['Assistant'])
    slot = asyncio.Semaphore(1)

    @routes.get('/api/assistant/status')
    def status():
        return {**settings(), 'local_tools':True, 'external_default':False}

    @routes.post('/api/projects/{pid}/assistant')
    async def ask(pid: str, body: AssistantQuery):
        path = storage.folder(pid)
        current = storage.read(path/'current.json')
        if not current:
            raise HTTPException(409, 'Сначала запустите анализ')
        nodes, dataset, summary, _, _ = await asyncio.to_thread(loaded, pid, current['hash'])
        def load_tools():
            requests = pd.read_csv(path/'results'/current['hash']/'requests.csv', dtype={'gid':str})
            return GraphTools(dataset=dataset, result_nodes=nodes, requests=requests, summary=summary)
        graph = await asyncio.to_thread(load_tools)
        graph.validate_gids(body.gids)
        if body.mode != 'question':
            return await asyncio.to_thread(graph.preset, body.mode, body.gids)
        if not body.allow_external:
            raise HTTPException(422, 'Подтвердите отправку вопроса и выбранных результатов в OpenAI для этого запроса.')
        if not settings()['configured']:
            raise HTTPException(503, 'Вопросы к ИИ не настроены. Локальные инструменты доступны без ключа.')
        if not body.question.strip():
            raise HTTPException(422,'Введите вопрос о выбранных узлах.')
        try:
            await asyncio.wait_for(slot.acquire(), timeout=.1)
        except TimeoutError:
            raise HTTPException(429, 'Ассистент уже отвечает. Дождитесь завершения.')
        try:
            return await asyncio.wait_for(ask_openai(graph,body.gids,body.question),timeout=60)
        except AssistantUnavailable as exc:
            raise HTTPException(503,str(exc)) from None
        except ValueError:
            raise HTTPException(422,'Проверьте вопрос и выбранные узлы.') from None
        except TimeoutError:
            raise HTTPException(504,'Время ожидания ответа истекло; локальные инструменты доступны.') from None
        except Exception as exc:
            # Never expose provider messages, request bodies, headers or credentials.
            status, message = provider_error_details(exc) or (502,'Не удалось получить ответ ассистента. Проверьте настройки API.')
            raise HTTPException(status,message) from None
        finally:
            slot.release()
    return routes
