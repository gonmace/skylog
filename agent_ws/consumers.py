import json
import logging

from channels.generic.websocket import AsyncWebsocketConsumer
from channels.db import database_sync_to_async
from django.contrib.auth.models import AnonymousUser

from .auth import get_user_from_ws_scope

log = logging.getLogger(__name__)


class AgentConsumer(AsyncWebsocketConsumer):

    async def connect(self):
        user, employee = await database_sync_to_async(get_user_from_ws_scope)(self.scope)

        if isinstance(user, AnonymousUser) or employee is None:
            log.warning('WS rechazado: token inválido o sin perfil de empleado')
            await self.close(code=4001)
            return

        if employee.is_executive:
            log.warning('WS rechazado: los ejecutivos no ejecutan agente (employee_id=%s)', employee.pk)
            await self.close(code=4003)
            return

        self.employee_id = employee.pk
        self.group_name = f'agent_{employee.pk}'

        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await database_sync_to_async(self._set_online)(True)
        await self.accept()
        log.info('Agente WS conectado: employee_id=%s', self.employee_id)

    async def disconnect(self, close_code):
        if hasattr(self, 'group_name'):
            await self.channel_layer.group_discard(self.group_name, self.channel_name)
            await database_sync_to_async(self._set_online)(False)
            log.info('Agente WS desconectado: employee_id=%s code=%s', self.employee_id, close_code)

    def _set_online(self, online: bool):
        from employees.models import Employee
        Employee.objects.filter(pk=self.employee_id).update(agent_online=online)

    async def receive(self, text_data):
        # Los agentes no envían comandos al servidor por WS.
        pass

    async def capture_command(self, event):
        """Reenvía un comando de captura al agente conectado."""
        await self.send(text_data=json.dumps({'command': event.get('command', 'capture')}))
        log.info('Comando de captura enviado al agente employee_id=%s', self.employee_id)
