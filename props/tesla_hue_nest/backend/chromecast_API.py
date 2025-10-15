
import numpy as np
import time
import asyncio
import colorsys
import pychromecast
from pychromecast.const import MESSAGE_TYPE
from pychromecast.response_handler import WaitResponse
import threading
import random

import ipdb

# STRANGE BEHAVIOUR:
# REPEAT only works with a queue.
# To initiate a queue, first load a media.
# This first media has to be playing, in order to add a second
# media and form a queue.
# Once a queue has been formed, we can issue the QUEUE_REPEAT commands.
#
# For example this should work:
# cc_group.load_media(url_list=['http://10.67.1.254:8000/Thriller-Laugh%20-%20original.mp3'], enqueue=False, autoplay=True)
# cc_group.load_media(url_list=['http://10.67.1.254:8000/Thriller-Laugh%20-%20original.mp3'], enqueue=True, autoplay=True)
# cc_group.queue_repeat_single()


# def seek(castunit, position, resumeState="PLAYBACK_PAUSE"):
#     """Seek the media to a specific location."""
#     castunit.media_controller._send_command(
#         {
#             MESSAGE_TYPE: "SEEK",
#             "currentTime": position,
#             "resumeState": resumeState,
#         }
#     )


def seek(castunit, position: float, resumeState: str = "PLAYBACK_PAUSE", timeout: float = 10.0) -> None:
    """Seek the media to a specific location."""
    response_handler = WaitResponse(timeout, f"seek {position}")
    castunit.media_controller._send_command(
        {
            MESSAGE_TYPE: "SEEK",
            "currentTime": position,
            "resumeState": resumeState,
        },
        response_handler.callback,
    )
    response_handler.wait_response()



QUEUE_REPEAT_OFF = "REPEAT_OFF"
QUEUE_REPEAT_ALL = "REPEAT_ALL"
QUEUE_REPEAT_SINGLE = "REPEAT_SINGLE"
QUEUE_REPEAT_ALL_AND_SHUFFLE = "REPEAT_ALL_AND_SHUFFLE"


def queue_repeat(castunit, repeatMode: str, timeout: float = 10.0) -> None:
    """Send QUEUE repeat command."""
    response_handler = WaitResponse(timeout, f"set repeat mode {repeatMode}")
    castunit.media_controller._send_command(
        {
            MESSAGE_TYPE: "QUEUE_UPDATE",
            "resumeMode": repeatMode,
        },
        response_handler.callback,
    )
    response_handler.wait_response()


class ChromecastGroup:
    TIMEOUT = 10  # seconds

    def __init__(self, host_list, volumes=None):
        chromecast_devices, browser = pychromecast.get_chromecasts(known_hosts=host_list)
        if not chromecast_devices:
            print(f'No chromecasts discovered')
        else:
            print('Found {0} devices.'.format(browser.count))
        self.browser = browser
        self.chromecasts = list(filter(lambda item: item.cast_info.host in host_list, chromecast_devices))
        if volumes is not None:
            self.default_volumes = volumes
        else:
            self.default_volumes = [0.3 for n in host_list]

        for id, cast in enumerate(self.chromecasts):
            # Start socket client's worker thread and wait for initial status update
            cast.wait()
            try:
                cast.media_controller.stop()
            except pychromecast.RequestFailed as e:
                print(f'Failed to stop media controller: {e}')

            cast.set_volume(self.default_volumes[id])
            print(f'Found chromecast with name "{cast.cast_info.friendly_name}"')

    #def __del__(self):
    #    self.browser.stop_discovery()

    def is_empty(self):
        return len(self.chromecasts) == 0

    def load_media(self, url_list, enqueue=False, autoplay=False):
        print('my_chromecast::load_media:  Number of chromecasts: {0}'.format(len(self.chromecasts)))
        for cid, cast in enumerate(self.chromecasts):
            print('my_chromecast::load_media:  {0}: {1}'.format(cid, self.chromecasts[cid].cast_info.host))

            if cid >= len(url_list):
                url = url_list[-1]  # take last item, if there is not enough
            else:
                url = url_list[cid]
            
            initial_player_state = cast.media_controller.status.player_state
            
            print("Loading media: "+cast.cast_info.host)
            cast.media_controller.play_media(url, "audio/mp3", autoplay=autoplay, enqueue=enqueue)
            
            if (not autoplay) and (initial_player_state != 'PLAYING'):
                print("Waiting for paused status: "+cast.cast_info.host)
            else:
                print("Waiting for playing status: "+cast.cast_info.host)
            
            current_time = time.monotonic()
            while cast.media_controller.status.player_state in ['UNKNOWN', 'IDLE', 'BUFFERING']:
                print(cast.media_controller.status.player_state)
                cast.media_controller.update_status()
                if time.monotonic() - current_time > self.TIMEOUT:
                    break
                time.sleep(0.5)

            cast.media_controller.update_status()
            if not autoplay  and (initial_player_state != 'PLAYING'):
                if cast.media_controller.status.player_state == 'PAUSED':
                    print("Paused status reported: "+cast.cast_info.host)
                    continue
            else: 
                if cast.media_controller.status.player_state == 'PLAYING':
                    print("Playing status reported: "+cast.cast_info.host)
                    continue
                elif cast.media_controller.status.player_state == 'PAUSED':
                    print("Paused status reported: "+cast.cast_info.host)
                    if autoplay:
                        print("Sending play request: "+cast.cast_info.host)
                        cast.media_controller.play()
                    continue
            
            print(" ")
            print("Debug info:")    
            print(f"Host: {cast.cast_info.host}")
            print(f"Host status: {cast.media_controller.status}")
            print(f"Host initial player state: {initial_player_state}")
            print(f"Host player state: {cast.media_controller.status.player_state}")
            print(f"Audoplay requested: {autoplay}")
            raise ValueError('Unexpected player state')

    def stop(self):
        for cast in self.chromecasts: 
            print("stop playing: "+cast.cast_info.host)
            try:
                cast.media_controller.stop()
            except pychromecast.RequestFailed as e:
                print(f'Failed to stop media controller: {e}')

    def play(self):
        for cast in self.chromecasts: 
            print("start playing: "+cast.cast_info.host)
            cast.media_controller.play()

    def pause(self):
        for cast in self.chromecasts: 
            print("pausing: "+cast.cast_info.host)
            cast.media_controller.pause()

    def seek(self, position=0, resume_state='PLAYBACK_PAUSE'):
        for cast in self.chromecasts: 
            seek(cast, position, resumeState=resume_state)

    def refresh(self):
        for cast in self.chromecasts: 
            cast.media_controller.update_status()

    def set_volume(self, volume=None):
        if volume is not None: 
            print("Setting all volumes to : {0:.1f}".format(volume))
        else:
            print('Setting default volumes')
            
        for id, cast in enumerate(self.chromecasts): 
            if volume is None:
                cast.set_volume(self.default_volumes[id])    
            else:
                cast.set_volume(volume)

    def volume_up(self):
        for id, cast in enumerate(self.chromecasts): 
            return cast.volume_up()

    def volume_down(self):
        for id, cast in enumerate(self.chromecasts): 
            return cast.volume_down()


    def any_playing(self):
        result = False
        for cast in self.chromecasts: 
            result = result or (cast.media_controller.status.player_state == 'PLAYING')
        return result

    def all_playing(self):
        result = True
        for cast in self.chromecasts: 
            result = result and (cast.media_controller.status.player_state == 'PLAYING')
        return result

    def any_paused(self):
        result = False
        for cast in self.chromecasts: 
            result = result or (cast.media_controller.status.player_state == 'PAUSED')
        return result

    def any_unknown(self):
        result = False
        for cast in self.chromecasts: 
            result = result or (cast.media_controller.status.player_state == 'UNKNOWN')
        return result

    def queue_repeat_single(self):
        for cast in self.chromecasts: 
            queue_repeat(cast, QUEUE_REPEAT_SINGLE)

    def queue_repeat_all(self):
        for cast in self.chromecasts: 
            queue_repeat(cast, QUEUE_REPEAT_ALL)
            
    def queue_repeat_off(self):
        for cast in self.chromecasts: 
            queue_repeat(cast, QUEUE_REPEAT_OFF)          

    def fade_to_stop(self, duration=5):
        self.refresh()

        max_vol = 0
        for cast in self.chromecasts:  
            if cast.status.volume_level > max_vol:
                max_vol = np.round(cast.status.volume_level, 2)

        fade_delay = 0.2 # duration/(max_vol*10) 
        while max_vol > 0:
            self.refresh()
            max_vol = 0
            for cast in self.chromecasts:
                if cast.media_controller.status.player_state == 'PLAYING':
                    if cast.status.volume_level > 0:
                        current_vol = cast.status.volume_level-0.1
                        cast.set_volume(current_vol)
                    else:
                        current_vol = 0
                    if (current_vol > 0) & (current_vol > max_vol):
                        max_vol = np.round(current_vol, 2)
            time.sleep(fade_delay)

        self.stop()
        for id, cast in enumerate(self.chromecasts):
            print('Resetting chromecast to default volume: '+cast.cast_info.host)
            cast.set_volume(self.default_volumes[id])

    def play_halloween2023(self):
        url = 'http://10.67.1.254:8000/Halloween%20soundtrack2023.mp3'
        self.load_media([url])
        time.sleep(3)
        self.play()

    #def play_thriller2022(self):
    #    url = 'http://10.67.1.254:32469/object/d463b8bdaf56cc8c9aea/file.mp3'
    #    await self.play_url(url, volume=volume)

    #def play_laugh2022(self):
    #    url = 'http://10.67.1.254:32469/object/feee8acf6e41a67b3ba9/file.mp3'
    #    await self.play_url(url, volume=volume)



if __name__ == "__main__":
    print('Connecting to Chromecasts...')    
    CHROMECAST_GREETER_IP = '10.67.1.252'
    CHROMECAST_BBQ_SKELETON_IP = '10.67.1.251'
    CHROMECAST_UNDECIDED_IP = '10.67.1.250'
    CHROMECAST_DUNGEON_IP = '10.67.1.253'

    KNOWN_HOSTS = [CHROMECAST_UNDECIDED_IP]

    group = ChromecastGroup(KNOWN_HOSTS)
    group.play_halloween2023()
