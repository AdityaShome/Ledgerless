"""A chain hop: performs one effect, then delegates to the next hop (A -> B -> C).

With the recovery extension: write-ahead intent, digest dedup, signed receipt returned in
message metadata. Without it (plain A2A client): just does the work.
"""

from __future__ import annotations

import uuid

import httpx
from a2a.client import ClientConfig, ClientFactory
from a2a.server.agent_execution import AgentExecutor, RequestContext
from a2a.server.events.event_queue_v2 import EventQueue
from a2a.types import Message, Part, Role, SendMessageRequest

from agents.tools.counter import EffectCounter
from recovery.a2a_middleware import recovery_block, with_recovery
from recovery.intents import Intent, compute_digest, make_intent
from recovery.service import RecoveryService


def reply(text: str, block: dict | None = None, ctx: RequestContext | None = None) -> Message:
    msg = Message(message_id=str(uuid.uuid4()), role=Role.ROLE_AGENT, parts=[Part(text=text)])
    if block:
        msg.metadata.CopyFrom(with_recovery(block))
    if ctx is not None:
        if ctx.context_id:
            msg.context_id = ctx.context_id
        if ctx.task_id:
            msg.task_id = ctx.task_id
    return msg


class ChainAgentExecutor(AgentExecutor):
    def __init__(
        self,
        name: str,
        service: RecoveryService,
        tool: EffectCounter,
        downstream_url: str | None = None,
        action_type: str = "do_work",
    ):
        self.name = name
        self.service = service
        self.tool = tool
        self.downstream_url = downstream_url
        self.action_type = action_type

    async def execute(self, context: RequestContext, event_queue: EventQueue) -> None:
        text = context.get_user_input()
        block = recovery_block(context.message.metadata if context.message else None)
        out: dict = {}

        if "intent" in block:
            intent = Intent.from_dict(block["intent"])
            state, receipt = self.service.begin(intent)
            if state == "proceed":
                ref = self.tool.apply(text)
                receipt = self.service.commit(intent, ref, intent.parent_receipt)
            out["status"] = state
            out["receipt"] = receipt.to_dict()
            if self.downstream_url and receipt.status == "committed":
                out["downstream"] = await self._delegate(text, intent.chain_id, receipt.hash)
        else:
            self.tool.apply(text)
            if self.downstream_url:
                out["downstream"] = await self._delegate(text, None, None)

        await event_queue.enqueue_event(reply(f"{self.name} done: {text}", out or None, context))

    async def _delegate(self, text: str, chain_id: str | None, parent_hash: str | None) -> dict:
        msg = Message(message_id=str(uuid.uuid4()), role=Role.ROLE_USER, parts=[Part(text=text)])
        if chain_id is not None:
            digest = compute_digest(self.action_type, "downstream", {"task": text})
            intent = make_intent(chain_id, digest, parent_receipt=parent_hash)
            msg.metadata.CopyFrom(with_recovery({"intent": intent.to_dict()}))
        async with httpx.AsyncClient(timeout=10) as http:
            config = ClientConfig(httpx_client=http, streaming=False)
            client = await ClientFactory(config).create_from_url(self.downstream_url)
            async for resp in client.send_message(SendMessageRequest(message=msg)):
                if resp.HasField("message"):
                    return recovery_block(resp.message.metadata)
        return {}

    async def cancel(self, context: RequestContext, event_queue: EventQueue) -> None:
        raise NotImplementedError
