import logging
import json
import asyncio
from dotenv import load_dotenv
from livekit import rtc
from livekit.agents import (
    Agent,
    AgentServer,
    AgentSession,
    JobContext,
    JobProcess,
    cli,
    inference,
    room_io,
    function_tool, RunContext, UserInputTranscribedEvent,
)
from livekit.plugins import noise_cancellation, silero, simli
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit.agents import UserInputTranscribedEvent

logger = logging.getLogger("agent-Sage-abb")
load_dotenv(".env.local")
SILENCE_TIMEOUT = 25

class DefaultAgent(Agent):
    def __init__(self,user_name: str,topic: str, level: str) -> None:
        self.user_name = user_name
        self.topic = topic
        self.level = level
        self.turn_count = 0
        self.max_turns = 10
        self.silence_task = None
        super().__init__(
            instructions=f"""You are a friendly {self.level} level language tutor. 
        The current lesson topic is: {self.topic}.

        - Always greet {self.user_name} by name in the First response only.
        - After the first response, do NOT use their name again unless I explicitly ask you to.
        - Listen closely to the user's grammar and pronunciation.
        - If the user makes a mistake, politely correct them before moving on.
        - Respond in plain text only, no markdown or emojis.
        - Run exactly 5 practice interactions and ask if user wants to continue, if yes continue
        - I will decide when the lesson ends
        - Do NOT say goodbye yourself
        - Keep replies brief (1-3 sentences) and natural for TTS.""",
        )

    @function_tool()
    async def end_call(self, context: RunContext) -> None:
        """Use this tool when the user has signaled they wish to end the current call."""
        await context.session.say(
            "Great job today. Complete the next episode to begin again!. Goodbye!",
            allow_interruptions=False,
        )
        await context.wait_for_playout()  # Ensure the agent finishes their current speech
        await context.session.aclose()



    # async def on_message(self, message: str):
    #     self.practice_count += 1
    #     logger.info(f"Practice turn {self.practice_count}: {message}")
    #
    #     if self.practice_count >= 5:
    #         # HARD guarantee — no LLM dependency
    #         await self.end_call(RunContext(session=self.session))
    async def handle_turn(self, session: AgentSession):
        """Increment turn count and end call if max_turns reached."""
        self.turn_count += 1
        logger.info(f"Turn {self.turn_count}/{self.max_turns}")
        # Reset the silence timer
        await self.reset_silence_timer(session)
        if self.turn_count >= self.max_turns:
            logger.info("Max turns reached, ending call")
            await session.say(
                "Great job today. Complete the next episode to begin again!. Goodbye!",
                allow_interruptions=False,
            )
            #await session.wait_for_playout()
            # Close the session -> disconnect the call
            session.shutdown(drain=True)

    async def reset_silence_timer(self, session: AgentSession):
        # Cancel any existing silence timer
        if self.silence_task and not self.silence_task.done():
            self.silence_task.cancel()
        # Start a new silence timer
        self.silence_task = asyncio.create_task(self.start_silence_timer(session))

    async def start_silence_timer(self, session: AgentSession):
        try:
            await asyncio.sleep(SILENCE_TIMEOUT)
            logger.info(f"No speech detected for {SILENCE_TIMEOUT} seconds, ending session")
            await session.say(
                "I noticed you’ve been silent for a while. Let’s continue next time. Goodbye!",
                allow_interruptions=False,
            )
            session.shutdown(drain=True)
        except asyncio.CancelledError:
            # Silence timer was reset because user spoke
            pass

    async def on_enter(self):
        """Called when the agent session starts; we override to greet user."""
        logging.info(f"Agent starting with user_id on_enter: {self.user_name}")
        # Start the silence timer immediately
        asyncio.create_task(self.reset_silence_timer(self.session))
        await self.session.say(
            f"Hello {self.user_name}! Welcome to Parlo. I’m Jessica, your English Grammar and Pronunciation Coach. We are starting our {self.level} lesson on {self.topic}. Are you ready to begin?",
            allow_interruptions=True,
        )


server = AgentServer()


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


server.setup_fnc = prewarm


@server.rtc_session(agent_name="test-agent")
async def entrypoint(ctx: JobContext):
    # 1. Access the raw metadata string
    raw_metadata = ctx.job.metadata

    # 2. Parse the JSON string into a Python dict
    try:
        # Defaults to an empty dict if metadata is empty/None
        metadata = json.loads(raw_metadata) if raw_metadata else {}

        # 3. Access your hardcoded keys
        user_name = metadata.get("user_name", "There")
        topic = metadata.get("topic", "Ordering at a Restaurant"),
        level = metadata.get("level", "intermediate")
        logging.info(f"Agent starting with user_id: {user_name}")

    except json.JSONDecodeError:
        logging.error("Failed to parse metadata JSON")
        metadata = {}
    session = AgentSession(
        stt=inference.STT(model="assemblyai/universal-streaming", language="en"),
        llm=inference.LLM(model="openai/gpt-4.1-mini"),
        tts=inference.TTS(
            model="inworld/inworld-tts-1",
            voice="Elizabeth",
            language="en",
        ),
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        preemptive_generation=True,
        use_tts_aligned_transcript=True,
    )

    # ---- Create DefaultAgent instance ----
    agent_instance = DefaultAgent(user_name=user_name, topic=topic, level=level)

    # ---- ADD EVENT LISTENER HERE ----
    @session.on("user_input_transcribed")
    def on_user_input_transcribed(event: UserInputTranscribedEvent):
        # Reset silence timer on any speech
        asyncio.create_task(agent_instance.reset_silence_timer(session))
        print(
            f"User input transcribed: {event.transcript}, "
            f"language: {event.language}, "
            f"final: {event.is_final}, "
            f"speaker id: {event.speaker_id}"
        )

        if not event.is_final:
            return

        payload = {
            "type": "user_transcript",
            "text": event.transcript,
            "language": event.language,
            "speaker_id": event.speaker_id,
        }

        asyncio.create_task(
            ctx.room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                topic="transcript",
            )
        )

        asyncio.create_task(agent_instance.handle_turn(session))

    @session.on("conversation_item_added")
    def on_conversation_item_added(event):
        # Extract the ChatMessage object
        item = getattr(event, "item", None)
        if item is None:
            return

        # Only process agent messages
        if getattr(item, "role", None) != "assistant":
            return

        # Join content list into a single string
        text = " ".join(item.content) if getattr(item, "content", None) else ""

        payload = {
            "type": "agent_transcript",
            "text": text,
        }

        # Print payload nicely
        import json
        print(json.dumps(payload, indent=2))

        # Forward to client
        asyncio.create_task(
            ctx.room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                topic="transcript",
            )
        )

    # Start session
    await session.start(
        agent=agent_instance,
        room=ctx.room,
        room_options=room_io.RoomOptions(
            audio_input=room_io.AudioInputOptions(
                noise_cancellation=lambda params: noise_cancellation.BVCTelephony()
                if params.participant.kind == rtc.ParticipantKind.PARTICIPANT_KIND_SIP
                else noise_cancellation.BVC(),
            ),
        ),
    )

    # Connect to the room (triggers on_enter and welcome message)
    await ctx.connect()


if __name__ == "__main__":
    cli.run_app(server)