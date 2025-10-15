# server/worker_host/builtin_workers/heartbeat.py
from __future__ import annotations
import asyncio
import queue
import time
from abc import ABC, abstractmethod 
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings
from typing import List

from worker_host.base import BaseWorker

# Import third-party libraries
from .chromecast_API import *
from .hue_API import *
from .tesla_API import *

PROP_ID = "tesla_hue_nest_worker"


# ============================ CONFIG MODEL ============================
class ChromecastDevice(BaseModel):
    IP: str
    volume: float = 0.5
    url: str
    repeat: bool = False

class ConfigModel(BaseSettings):
    TESLA_AUTH_TOKEN: str = Field(..., env="TESLA_AUTH_TOKEN")
    VEHICLE_TAG: str = Field(..., env="VEHICLE_TAG")
    HUE_BRIDGE_IP: str = Field(..., env="HUE_BRIDGE_IP")
    MOTION_SENSORS: List[str]
    CHROMECAST_TESLA_GROUP: List[ChromecastDevice]
    USE_TESLA: bool = False
    WAIT_BETWEEN_PLAYS: int = 480
    MOTION_TIMEOUT: int = 180
    HUE_SPOT_LIGHT: str = "Halloween Tesla"
    tick_interval: int = 5

    # Use BaseSettings' model_config to control env file behavior. Docker
    # already supplies environment variables via docker-compose env_file,
    # so explicit env_file is optional. Keep env_file here for local dev.
    model_config = {
        "env_file": ".env",
        "env_file_encoding": "utf-8",
        # ignore extra keys from the raw YAML to be lenient
        "extra": "ignore",
    }


# ============================ STATE CLASSES ============================
class State(ABC):
    """
    Abstract base class for a state in the state machine.

    This class defines the interface for all concrete states. It ensures that
    any state implementation provides a `handle` method. It also provides
    default, overridable handlers for actions and motion events.
    """
    def __init__(self, context):
        """Initializes the state."""
        pass 

    @abstractmethod
    def handle(self, context):
        """
        Executes the primary logic for the state on each tick of the poll loop.

        This method must be implemented by all concrete state subclasses.

        Args:
            context: The main Worker instance, providing access to shared resources.
        """
        pass

    def on_action(self, context, action, arg):
        """
        Handles a command received from the MQTT command queue.

        This method can be overridden by subclasses to define state-specific
        command handling.

        Args:
            context: The main Worker instance.
            action: The command action string (e.g., 'arm', 'stop').
            arg: An optional argument string for the command.
        """
        print(f"{self.__class__.__name__}::action passed: {action}, arg: {arg}")

    def on_motion(self, context):
        """
        Handles a motion detection event.

        This method can be overridden by subclasses to define state-specific
        responses to motion.

        Args:
            context: The main Worker instance.
        """
        # Which sensors triggered the event can be accessed from 
        # context.motion_listener.triggered_sensors
        pass
        #print(f"{self.__class__.__name__}::Motion detected.")


class StoppedState(State):
    """
    Represents the idle state of the system.

    In this state, all prop activities are ceased (lights off, trunk closed,
    media stopped). The worker waits for an 'arm' command to begin the sequence.
    """
    def __init__(self, context):
        """Initializes the stopped state, ensuring a clean shutdown of all components."""
        print("System is stopped. Waiting for input...")
        self.stopped = False

    def handle(self, context):
        """
        Ensures all prop components are in their off/idle state.

        This method runs once upon entering the state and then does nothing
        further, preventing repeated "off" commands.
        """
        if not self.stopped:
            context.hue_manager.lights.disco_on = False
            context.hue_manager.lights.send_command('purple', transitiontime=1)

            if context.config.USE_TESLA:
                context.tesla_car.close_trunk(trunk_check=True)

            if context.cc_tesla_group is not None and not context.cc_tesla_group.is_empty():
                context.cc_tesla_group.stop()

            context.hue_manager.lights_off(transitiontime=1)
            self.stopped = True

    def on_action(self, context, action, arg):
        """Handles user commands while in the stopped state."""
        print(f"{self.__class__.__name__}::action passed: {action}, arg: {arg}")
        match action:
            case 'disco':
                context.hue_manager.toggle_disco()
            case 'arm':
                context.set_state(ArmingState)
            case 'volume_up':
                if not context.cc_tesla_group.is_empty():
                    context.cc_tesla_group.volume_up()
            case 'volume_down':
                if not context.cc_tesla_group.is_empty():
                    context.cc_tesla_group.volume_down()


class ArmingState(State):
    """
    Prepares the system for operation.

    This state loads the necessary media onto the Chromecast devices and then
    immediately transitions to the WaitingState.
    """
    def __init__(self, context):
        """Initializes the arming state."""
        print("System is arming...")

    def handle(self, context):
        """
        Loads media onto the Chromecast group and transitions to WaitingState.
        """
        # Load thriller sound track if possible
        if context.cc_tesla_group.is_empty():
            print('No Tesla chromecast found, cannot play media.')
        else:
            context.cc_tesla_group.load_media(url_list=filter_url_list(context.config.CHROMECAST_TESLA_GROUP))
            print('Tesla media loaded and ready...')

        context.set_state(WaitingState)

    def on_action(self, context, action, arg):
        print(f"{self.__class__.__name__}::action passed: {action}, arg: {arg}")
        match action:
            case 'wait':
                context.set_state(WaitingState)

class WaitingState(State):
    """
    Waits for motion to be detected.

    This state is the main "armed and ready" mode. It periodically checks
    the status of the Chromecast devices to ensure they are ready. If motion
    is detected, it transitions to the PlayingState.
    """
    def __init__(self, context):
        """Initializes the waiting state."""
        print("System is waiting for motion...")
        self.check_interval = 60  # Check interval in seconds
        self.last_check_time = time.monotonic()

    def handle(self, context):
        """
        Periodically checks Chromecast status to prevent timeouts or errors.
        """
        current_time = time.monotonic()
        if current_time - self.last_check_time > self.check_interval:
            context.cc_tesla_group.refresh()
            if context.cc_tesla_group.any_unknown():
                print(f"{self.__class__.__name__}::Unknown chromecast state detected. Rearming...")
                context.set_state(ArmingState)
                return
            self.last_check_time = current_time
            print(f"{self.__class__.__name__}::Checked chromecast state, all good!")

    def on_action(self, context, action, arg):
        """Handles user commands while waiting for motion."""
        print(f"{self.__class__.__name__}::action passed: {action}, arg: {arg}")
        match action:
            case 'stop':
                context.set_state(StoppedState)
            case 'play':
                context.set_state(PlayingState)
    
    def on_motion(self, context):
        """Transitions to the PlayingState upon motion detection."""
        context.set_state(PlayingState)


class CooldownState(State):
    """
    Enforces a delay between prop activations.

    This state does nothing for a fixed duration, preventing the prop from
    triggering too frequently. It then transitions back to the ArmingState.
    """
    def __init__(self, context):
        """Initializes the cooldown timer."""
        print("Entering cooldown state for 30 seconds...")
        self.cooldown_end_time = time.monotonic() + 30

    def handle(self, context):
        """
        Checks if the cooldown period has elapsed and transitions if so.
        """
        if time.monotonic() >= self.cooldown_end_time:
            print("Cooldown finished. Re-arming.")
            context.set_state(ArmingState)

    def on_action(self, context, action, arg):
        """Allows the prop to be stopped manually during cooldown."""
        # Allow stopping during cooldown
        if action == 'stop':
            context.set_state(StoppedState)


class PlayingState(State):
    """
    Executes the main prop sequence.

    This state plays media, controls lights, and opens the Tesla trunk. It
    includes a timeout to transition to FadeOutState if motion is no longer
    detected.
    """
    def __init__(self, context):
        """
        Initializes the playing sequence.

        Checks if the cooldown period has passed. If so, it starts the media,
        opens the trunk, and sets the lights. If not, it transitions to the
        CooldownState.
        """
        self.wait_between_plays = context.config.WAIT_BETWEEN_PLAYS
        self.timeout_interval = context.config.MOTION_TIMEOUT  # Timeout interval in seconds
        self.last_motion_time = time.monotonic()

        # Check if WAIT_BETWEEN_PLAYS seconds have passed since last play
        delta_time = time.monotonic() - context.time_of_last_play
        if delta_time < self.wait_between_plays:
            # --- REFACTORED ---
            # Instead of sleeping, transition to the new CooldownState
            context.set_state(CooldownState)
            return
        
        if context.config.USE_TESLA:
            context.tesla_car.get_vehicle_state()

        print("System is playing...")
        context.time_of_last_play = time.monotonic()
        context.play_counter += 1
        context.hue_manager.send_command('purple')

        if not context.cc_tesla_group.is_empty():
            context.cc_tesla_group.play()
        
        if context.config.USE_TESLA:
            context.tesla_car.open_trunk()

    def handle(self, context):
        """
        Monitors for inactivity timeout and media completion.

        If no motion is detected for the timeout duration, or if the media
        finishes playing, it transitions to the FadeOutState.
        """
        current_time = time.monotonic()
        if current_time - self.last_motion_time > self.timeout_interval:
            # Trigger timeout if enough time has passed since the last motion detection
            print("Timeout triggered due to inactivity.")
            context.set_state(FadeOutState)
        print(f"{self.__class__.__name__}::Time since last motion: {current_time - self.last_motion_time:.1f} s")
        
        if not context.cc_tesla_group.is_empty():
            context.cc_tesla_group.refresh()
            if not context.cc_tesla_group.any_playing():
                print("Soundtrack stopped playing...")
                context.set_state(FadeOutState)

    def on_action(self, context, action, arg):
        """Handles user commands during the playing sequence."""
        print(f"{self.__class__.__name__}::action passed: {action}, arg: {arg}")
        match action:
            case 'stop':
                context.set_state(StoppedState)
            case 'fade':
                context.set_state(FadeOutState)
            case 'disco':
                context.hue_manager.toggle_disco()
            case 'reset':
                self.last_motion_time = time.monotonic()
            case 'volume_up':
                if not context.cc_tesla_group.is_empty():
                    context.cc_tesla_group.volume_up()
            case 'volume_down':
                if not context.cc_tesla_group.is_empty():
                    context.cc_tesla_group.volume_down()

    def on_motion(self, context):
        """Resets the inactivity timer upon motion detection."""
        self.last_motion_time = time.monotonic()


class FadeOutState(State):
    """
    Gracefully ends the prop sequence.

    This state fades out the media volume, closes the Tesla trunk, and fades
    the lights to off over a set transition time before re-arming.
    """
    def __init__(self, context):
        """Initializes the fade-out sequence."""
        print("Fading out...")
        self.transition_time = 10 # seconds for lights to fade
        self.next_state_time = time.monotonic() + self.transition_time

        context.hue_manager.lights.disco_on = False
        context.hue_manager.lights.send_command('purple', transitiontime=self.transition_time * 10) # phue uses 1/10s

        if context.config.USE_TESLA:
            context.tesla_car.close_trunk(trunk_check=True)

        if context.cc_tesla_group is not None and not context.cc_tesla_group.is_empty():
            context.cc_tesla_group.fade_to_stop()

        context.hue_manager.lights_off(transitiontime=self.transition_time)

    def handle(self, context):
        """
        Waits for the fade-out transition to complete, then re-arms.
        """
        # This state's work is done in __init__. We just wait here.
        if time.monotonic() >= self.next_state_time:
            context.set_state(ArmingState)

    def on_action(self, context, action, arg):
        """Allows the prop to be stopped manually during fade-out."""
        print(f"{self.__class__.__name__}::action passed: {action}, arg: {arg}")
        match action:
            case 'stop':
                context.set_state(StoppedState)


# ============================ HUE MANAGER ============================
class HueManager:
    """
    A wrapper for the HueLights object to provide a simplified API.

    This class abstracts the details of sending commands to the Hue bridge,
    managing the disco mode, and turning lights off.
    """
    def __init__(self, lights):
        """
        Initializes the HueManager.

        Args:
            lights: An initialized HueLights object.
        """
        self.lights = lights

    def toggle_disco(self):
        """Toggles the disco mode on or off."""
        if self.lights.disco_on:
            self.lights.disco_on = False
            self.lights.send_command('red')
            print('Stopping disco...')
        else:
            self.lights.start_disco()
            print('Starting disco...')

    def send_command(self, command):
        """Sends a raw command to the Hue lights."""
        self.lights.send_command(command)

    def lights_off(self, transitiontime=0):
        """
        Turns the lights off.

        Args:
            transitiontime: The time in seconds for the lights to fade out.
        """
        self.lights.lights_off(transitiontime=transitiontime)


# ======= Resiliency helpers: dummy subsystems used when hardware is unavailable ======
class _DummyLights:
    def __init__(self):
        self.disco_on = False
    def send_command(self, *a, **k):
        return None
    def lights_off(self, *a, **k):
        return None
    def start_disco(self):
        self.disco_on = True


class _NullHueManager:
    def __init__(self):
        self.lights = _DummyLights()
    def toggle_disco(self):
        return None
    def send_command(self, *a, **k):
        return None
    def lights_off(self, *a, **k):
        return None


class _DummyChromecastGroup:
    def __init__(self):
        pass
    def is_empty(self):
        return True
    def load_media(self, *a, **k):
        return None
    def stop(self):
        return None
    def play(self):
        return None
    def refresh(self):
        return None
    def any_unknown(self):
        return False
    def any_playing(self):
        return False
    def volume_up(self):
        return None
    def volume_down(self):
        return None
    def fade_to_stop(self):
        return None


# ============================ UTILS ============================
# Utility Functions
def _get_field_from_item(item, field):
    """Return field value from dict-like or object-like item."""
    try:
        # dict-like
        if isinstance(item, dict):
            return item.get(field)
        # pydantic BaseModel or simple object
        return getattr(item, field, None)
    except Exception:
        return None

def filter_ip_list(list_of_items):
    """Extract IP addresses from list of dicts or objects (ChromecastDevice)."""
    return [_get_field_from_item(it, 'IP') for it in list_of_items]

def filter_url_list(list_of_items):
    """Extract URLs from list of dicts or objects."""
    return [_get_field_from_item(it, 'url') for it in list_of_items]

def filter_volume_list(list_of_items):
    """Extract volume values from list of dicts or objects."""
    return [_get_field_from_item(it, 'volume') for it in list_of_items]

def filter_repeat_list(list_of_items):
    """Extract repeat flags from list of dicts or objects."""
    return [_get_field_from_item(it, 'repeat') for it in list_of_items]

def connect_hue_lights(bridge_ip, light_name):
    """
    Connects to the Hue bridge and returns a HueLights object.

    Args:
        bridge_ip: The IP address of the Hue bridge.
        light_name: The name of the light or group to control.

    Returns:
        An initialized HueLights object.
    """
    lights = HueLights(bridge_ip, light_name)
    lights.send_command('off')
    return lights

# ============================ WORKER CLASS ============================

class Worker(BaseWorker):
    """
    Orchestrates the Tesla/Hue/Nest prop.

    This worker manages a state machine that controls interactions between a
    Tesla vehicle, Philips Hue lights, and Google Chromecast devices. It listens
    for MQTT commands to start, stop, and control the prop sequence, and it
    responds to motion sensor events.
    """

    NAME = "tesla_hue_nest_worker"

    def __init__(self, prop_id, mqtt_client, config: ConfigModel | None = None):
        """
        Initializes the worker, loading configuration and setting up state variables.

        This constructor is non-blocking. All I/O-bound initializations for
        external services are deferred to the `start` method.

        Args:
            prop_id: The unique identifier for this prop.
            mqtt_client: The MQTT client instance for communication.
            config: A Pydantic model of the configuration options for the worker,
                    loaded from the prop's config.yml file.
        """
        super().__init__(prop_id, mqtt_client, config)
        
        self.current_state = None # Will hold the state object instance
        self.command_queue = queue.Queue() # Will hold incoming commands

        # State Machine Variables
        self.play_counter = 0
        self.time_of_last_play = time.monotonic() - 600    # set it to 10 minutes ago


    # --- NEW: State Management Method ---
    def set_state(self, new_state_class):
        """
        Transitions the worker to a new state and notifies via MQTT.

        This method is the central point for all state changes. It creates an
        instance of the new state class, updates the worker's current state,
        and publishes the new state name to the status topic.

        Args:
            new_state_class: The class of the state to transition to (e.g., `StoppedState`).
        """
        if self.current_state and self.current_state.__class__ == new_state_class:
            return # Already in this state

        state_name = new_state_class.__name__.replace("State", "").lower()
        print(f"Transitioning to state: {state_name}")
        
        # Create an instance of the new state, passing self as the context
        self.current_state = new_state_class(self)
        
        # Publish the new state via MQTT
        self.status("state", state_name)   

    # --- NEW: Async Command Bridge ---
    async def do_command(self, action: str | None, arg: str | None):
        """
        Receives a command from MQTT and puts it on the thread-safe queue.

        This method serves as the bridge between the asynchronous MQTT message
        handler and the synchronous state machine. It queues commands to be
        processed by the main poll loop.

        Args:
            action: The command action string (e.g., 'arm', 'stop').
            arg: An optional argument string for the command.
        """
        if action:
            print(f"Queueing command: {action}({arg})")
            self.command_queue.put((action, arg))

    async def _init_integrations(self):
        """
        Initializes connections to all external services (Hue, Tesla, Chromecast).

        This method runs all blocking I/O calls in a separate thread to avoid
        freezing the main asyncio event loop during startup.

        Returns:
            True if all initializations succeed, False otherwise.
        """
        
        try:
            # Use to_thread for all blocking initializations
            await asyncio.to_thread(self._connect_blocking_services)
            
            # Set initial state only after connections are successful
            self.set_state(StoppedState)

        except Exception as e:
            print(f"FATAL: ERROR initializing integrations: {e}")
            self.status("state", "error")
            # Do not start the poll loop if init fails
            return False
        return True

    def _connect_blocking_services(self):
        """
        Contains the blocking I/O calls for service initialization.

        This method is executed in a separate thread via `asyncio.to_thread`
        to prevent blocking the main worker loop.
        """
        # Chromecast
        try:
            print('Connecting to sound system...')
            self.cc_tesla_group = ChromecastGroup(host_list=filter_ip_list(self.config.CHROMECAST_TESLA_GROUP),
                                                  volumes=filter_volume_list(self.config.CHROMECAST_TESLA_GROUP))
        except Exception as e:
            print(f"[tesla_hue_nest] Chromecast init failed: {e}. Continuing without sound system.")
            self.cc_tesla_group = _DummyChromecastGroup()

        # Hue (lights + motion sensors)
        try:
            print('Connecting to Hue...')
            self.hue_lights = connect_hue_lights(self.config.HUE_BRIDGE_IP, self.config.HUE_SPOT_LIGHT)
            self.hue_manager = HueManager(self.hue_lights)
            # motion_sensors are HueSensor instances; if Hue init fails, we won't have sensors
            self.motion_sensors = [HueSensor(self.config.HUE_BRIDGE_IP, name) for name in self.config.MOTION_SENSORS]
        except Exception as e:
            print(f"[tesla_hue_nest] Hue init failed: {e}. Continuing without lights/motion sensors.")
            self.hue_manager = _NullHueManager()
            # Provide an empty sensor list so polling won't crash
            self.motion_sensors = []

        # Tesla (optional)
        print('Connecting to Tesla...')
        if self.config.USE_TESLA:
            try:
                self.tesla_car = TeslaCar(self.config.TESLA_AUTH_TOKEN, self.config.VEHICLE_TAG)
                self.tesla_car.close_trunk(trunk_check=False)
            except Exception as e:
                print(f"[tesla_hue_nest] Tesla init failed: {e}. Continuing without Tesla integration.")
                self.tesla_car = None
        else:
            self.tesla_car = None

    async def start(self) -> None:
        """
        Starts the worker's main operations.

        This method is called by the worker_host. It initializes all external
        integrations and, upon success, spawns the background tasks for the
        ticker and the main polling loop.
        """
        await super().start()

        # --- Initialize integrations first ---
        init_success = await self._init_integrations()
        if not init_success:
            print("FATAL: Initialization failed.")
            return # Stop if initialization failed

        # Spawn ticker method
        self.spawn(self._ticker())

        # Spawn the async poll loop as a managed task
        self.spawn(self._poll_loop())

    async def do_exit(self, arg: str | None) -> None:
        """
        Gracefully stops the worker and cleans up resources.

        This method is triggered by an 'exit' command via MQTT. It runs the
        synchronous cleanup logic and then stops all background tasks.

        Args:
            arg: An optional argument string (not used).
        """
        print("Received exit command. Shutting down worker...")
        
        # Run the synchronous cleanup logic in a thread
        await asyncio.to_thread(self._cleanup_sync)
        
        # The BaseWorker's stop() method will cancel all spawned tasks
        await self.stop()
        print("Worker has been stopped.")

    def _cleanup_sync(self):
        """
        Contains the blocking I/O calls for resource cleanup.

        This method is executed in a separate thread to ensure that shutting
        down services does not block the main loop.
        """
        print("Cleaning up resources...")
        if hasattr(self, 'hue_manager'):
            self.hue_manager.lights_off()
        if hasattr(self, 'cc_tesla_group') and self.cc_tesla_group is not None:
            self.cc_tesla_group.stop()
        if hasattr(self, 'tesla_car') and self.config.USE_TESLA and self.tesla_car is not None:
            self.tesla_car.close_trunk(trunk_check=True)

    async def _poll_loop(self):
        """
        The main background loop for the worker.

        This loop continuously processes commands from the queue and delegates
        state logic and motion detection to the synchronous `_run_sync_tasks`
        method, which runs in a separate thread to avoid blocking the asyncio
        event loop.
        """
        while True:
            # --- Process Command Queue ---
            try:
                # Check for a command without blocking
                # The queue contains (action, arg) tuples
                action, arg = self.command_queue.get_nowait()
                self._handle_command(action, arg)
            except queue.Empty:
                pass # No command, continue on

            # --- Run Synchronous, Blocking Code in a Thread ---
            # This prevents your API calls (Hue, Tesla) from freezing the event loop.
            await asyncio.to_thread(self._run_sync_tasks)

            # Use the non-blocking sleep
            await asyncio.sleep(0.2)            
            

    def _run_sync_tasks(self):
        """

        Executes all synchronous, blocking tasks for the worker.

        This includes running the current state's `handle` method and polling
        the motion sensors. It is designed to be called via `asyncio.to_thread`
        from the main async poll loop.
        """
        # Delegate the main work to the current state's handle method
        if self.current_state:
            self.current_state.handle(self)

        # Poll for motion and delegate
        motion_detected = False
        for sensor in self.motion_sensors: # Corrected variable name from your __init__
            sensor.refresh()
            if sensor.presence:
                motion_detected = True
                break 
        
        if motion_detected:
            if self.current_state:
                self.current_state.on_motion(self)


    def _handle_command(self, action: str, arg: str | None):
        """
        Dispatches a queued command to the current state's `on_action` handler.

        Args:
            action: The command action string.
            arg: An optional argument string for the command.
        """
        if action and self.current_state and hasattr(self.current_state, 'on_action'):
            # Call the state's on_action method
            self.current_state.on_action(self, action, arg)
        else:
            print(f"Warning: No handler for action '{action}' or state has no on_action method.")


    async def _ticker(self):
        """
        A background task that periodically publishes a telemetry tick.

        This serves as a simple heartbeat to indicate that the worker is alive
        and running.
        """
        i = 0
        interval = int(self.config.tick_interval)
        try:
          while True:
              self.telemetry("tick", i)
              i += 1
              await asyncio.sleep(interval)
        except asyncio.CancelledError:
          # Optional: cleanup hardware, close files, etc.
          raise

    # --- Actions ---
    async def do_tesla(self, arg: str | dict | None):
        """
        Handles the 'tesla' command to perform Tesla-specific actions.

        Args:
            arg: A string or dictionary specifying the Tesla action to perform.
        """
        if not self.config.USE_TESLA:
            print("Tesla integration is disabled.")
            return
        elif self.tesla_car is None:
            print("Tesla car instance is not available.")
            return

        if isinstance(arg, str):
            action = arg.lower()
            match action:
                case 'open_trunk':
                    await asyncio.to_thread(self.tesla_car.open_trunk)
                case 'close_trunk':
                    await asyncio.to_thread(self.tesla_car.close_trunk, trunk_check=True)
                case 'lock':
                    await asyncio.to_thread(self.tesla_car.lock)
                case 'unlock':
                    await asyncio.to_thread(self.tesla_car.unlock)
                case 'flash_lights':
                    await asyncio.to_thread(self.tesla_car.flash_lights)
                case _:
                    print(f"Unknown Tesla action: {action}")
        elif isinstance(arg, dict):
            # Handle dictionary-based commands if needed
            print("Dictionary-based Tesla commands are not implemented.")
        else:
            print("Invalid argument for Tesla command.")

    async def do_hue(self, arg: str | dict | None):
        """
        Handles the 'hue' command to perform Hue light actions.

        Args:
            arg: A string or dictionary specifying the Hue action to perform.
        """
        if self.hue_manager is None:
            print("Hue manager instance is not available.")
            return

        if isinstance(arg, str):
            action = arg.lower()
            match action:
                case 'disco':
                    self.hue_manager.toggle_disco()
                case 'off':
                    self.hue_manager.lights_off()
                case 'purple':
                    self.hue_manager.send_command('purple')
                case 'red':
                    self.hue_manager.send_command('red')
                case 'green':
                    self.hue_manager.send_command('green')
                case 'blue':
                    self.hue_manager.send_command('blue')
                case _:
                    print(f"Unknown Hue action: {action}")
        elif isinstance(arg, dict):
            # Handle dictionary-based commands if needed
            print("Dictionary-based Hue commands are not implemented.")
        else:
            print("Invalid argument for Hue command.")

    async def do_chromecast(self, arg: str | dict | None):
        """
        Handles the 'chromecast' command to perform Chromecast actions.

        Args:
            arg: A string or dictionary specifying the Chromecast action to perform.
        """
        if self.cc_tesla_group is None or self.cc_tesla_group.is_empty():
            print("Chromecast group is not available.")
            return

        if isinstance(arg, str):
            action = arg.lower()
            match action:
                case 'play':
                    self.cc_tesla_group.play()
                case 'stop':
                    self.cc_tesla_group.stop()
                case 'volume_up':
                    self.cc_tesla_group.volume_up()
                case 'volume_down':
                    self.cc_tesla_group.volume_down()
                case 'fade_to_stop':
                    self.cc_tesla_group.fade_to_stop()
                case _:
                    print(f"Unknown Chromecast action: {action}")
        elif isinstance(arg, dict):
            # Handle dictionary-based commands if needed
            print("Dictionary-based Chromecast commands are not implemented.")
        else:
            print("Invalid argument for Chromecast command.")
        
        