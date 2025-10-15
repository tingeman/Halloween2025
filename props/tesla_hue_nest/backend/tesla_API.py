"""
my_tesla.py: Module to interact with Tesla vehicle via MyTeslaMate API.

Classes:
- MyTeslaMateAPI: Handles API requests to MyTeslaMate.
- TeslaCar: Represents a Tesla vehicle and provides methods to control it.

Exceptions:
- TeslaAPIError: Raised for general API errors.
- TeslaCarOfflineError: Raised when the vehicle is offline.

Usage:
- Instantiate TeslaCar with auth token and vehicle ID.
- Use methods to wake up vehicle, check status, and control trunk.  

Note:
- As of 2025-09-29, the 'rt' field in vehicle_state is unreliable for trunk status.
    it seems to always return 0. Instead, we use the door_lock command to check if the trunk is open.
"""

import time
import json
import ipdb
import http.client
from pathlib import PurePosixPath
from http.client import RemoteDisconnected


class TeslaAPIError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return f'TeslaAPIError: {self.message}'


class TeslaCarOfflineError(Exception):
    def __init__(self, message):
        self.message = message
        super().__init__(self.message)

    def __str__(self):
        return f'TeslaCarOfflineError: {self.message}'


class MyTeslaMateAPI:
    def __init__(self, token, vehicle_id):
        self.token = token
        self.vehicle_id = vehicle_id
        self.conn = http.client.HTTPSConnection("api.myteslamate.com")
        self.headers = {'Content-Type': 'application/json',
                        'Authorization': f"Bearer {self.token}"}
        self.basepath = PurePosixPath(f"/api/1/vehicles/{self.vehicle_id}")

    def post(self, path, payload=json.dumps({}), timeout=3):
        try:
            self.conn.request("POST", str(self.basepath/path), body=payload, headers=self.headers)
            res = self.conn.getresponse()
        except RemoteDisconnected as e:
            counter = 0
            while counter < timeout:
                try:
                    self.conn.request("POST", str(self.basepath/path), body=payload, headers=self.headers)
                    res = self.conn.getresponse()
                    break
                except RemoteDisconnected as e:
                    counter += 1
                    time.sleep(1)
                    continue
        response_str = res.read().decode("utf-8")
        response = json.loads(response_str)
        
        if not response['response']:
            if "vehicle unavailable" in response['error']:
                raise TeslaCarOfflineError(response['error'])
            else:
                raise TeslaAPIError(response['error'])
        else:
            return response['response']
        
    def get(self, path, timeout=3):
        try:
            self.conn.request("GET", str(self.basepath/path), headers=self.headers)
            res = self.conn.getresponse()
        except RemoteDisconnected as e:
            counter = 0
            while counter < timeout:
                try:
                    self.conn.request("GET", str(self.basepath/path), headers=self.headers)
                    res = self.conn.getresponse()
                    break
                except RemoteDisconnected as e:
                    counter += 1
                    time.sleep(1)
                    continue
        response_str = res.read().decode("utf-8")
        response = json.loads(response_str)
        #print(response)

        if not response['response']:
            if "vehicle unavailable" in response['error']:
                raise TeslaCarOfflineError(response['error'])
            else:
                raise TeslaAPIError(response['error'])
        else:
            return response['response']
            
    def wake_up(self):
        print(f"{self.__class__.__name__}::Sending wake up API command...")
        return self.post('wake_up')
    
    def vehicle(self):
        return self.get('')

    def is_online(self):
        return self.vehicle()['state'] == 'online'

    def vehicle_data(self):
        return self.get('vehicle_data')
    
    def actuate_trunk(self, which_trunk='rear'):
        payload = json.dumps({
            "which_trunk": which_trunk
        })
        return self.post('command/actuate_trunk', payload)
    
    def door_lock(self):
        return self.post('command/door_lock')
    

class TeslaCar:
    def __init__(self, token, vehicle_id):
        self.trunk_open = False
        self.token = token
        self.vehicle_id = vehicle_id
        self.api = MyTeslaMateAPI(self.token, self.vehicle_id)
        self.wake_up()
        self.close_trunk(trunk_check=True)    # ensure trunk state is known and close trunk if open
        self.identify()

    def wake_up(self, timeout=20):
        if not self.api.is_online():
            print(f"{self.__class__.__name__}::Vehicle is offline, attempting to wake up...")
            ipdb.set_trace()
            res = self.api.wake_up()
            time.sleep(1)
            counter = 1
            while not self.api.is_online():
                if counter > timeout:
                    raise TeslaCarOfflineError("Vehicle is still offline 20 sec after wake up")
                print(f"{self.__class__.__name__}::Waiting for vehicle to come online... {counter}s")
                time.sleep(1)
                counter += 1
            print(f"{self.__class__.__name__}::Vehicle is now online")

    def identify(self):
        self.get_vehicle_state()
        print(f"{self.__class__.__name__}::Identifying vehicle...")
        print(f"Name:         {self.vehicle_data['vehicle_state']['vehicle_name']}")
        print(f"State:        {self.vehicle_data['state']}")
        print(f"Charge state: {self.vehicle_data['charge_state']['battery_level']}%")
        #print(f"Rear trunk:   {self.vehicle_data['vehicle_state']['rt']}")   
        print(f"Rear trunk:   {'Open' if self.trunk_open else 'Closed'}")

    def get_vehicle_state(self, trunk_check=False):
        try:
            self.vehicle_data = self.api.vehicle_data()
        except TeslaCarOfflineError as e:
            self.wake_up()
            self.vehicle_data = self.api.vehicle_data()

        # set online state  
        self.online = self.vehicle_data['state'] == 'online'

        # If rear trunk is open, set trunk_open to True
        
        # Currently 'rt' is not relible as per 2025-09-29, so we use door_lock command to check trunk state
        if trunk_check:
            self.get_trunk_state()

        # Code to use 'rt' field, but it's not reliable as per 2025-09-29
        # if self.vehicle_data['vehicle_state']['rt'] > 0:
        #     self.trunk_open = True    
        # else:
        #     self.trunk_open = False

    def open_trunk(self):
        if not self.trunk_open:
            self.wake_up()
            try:
                res = self.api.actuate_trunk(which_trunk='rear')
            except (TeslaAPIError, TeslaCarOfflineError) as e:
                print(e)
                return
            
            if res['result'] == True:
                self.trunk_open = True
                print(f"{self.__class__.__name__}::Trunk opened")
            else:
                print(f"{self.__class__.__name__}::Failed to open trunk")
        else:
            print(f"{self.__class__.__name__}::Trunk is already open")

    def get_trunk_state(self):
        """
        Check if trunk is open by sending door_lock command.
        If trunk (or any door) is open, the LOCK command will fail with 'CLOSURES_OPEN' error.
        
        We currently assume that if LOCK command fails with 'CLOSURES_OPEN', it's because the trunk is open.
        This is a workaround because 'rt' field is not reliable as of 2025-09-29.

        This command will result in the doors being locked if they were not already locked and no doors were open.
        """
        self.wake_up()
        response = self.api.door_lock()
        if response['result'] == False and 'CLOSURES_OPEN' in response['string']:
            self.trunk_open = True
        else:
            self.trunk_open = False
    
    # def confirm_trunk_open(self):
    #     if self.command('LOCK') == 'doors_open':
    #         # this is a workaround to check if trunk is open
    #         # if trunk is open (or other door), the LOCK command will fail
    #         self.trunk_open = True
    #         return True
    #     else:
    #         self.trunk_open = False
    #         return False

    def close_trunk(self, trunk_check=True):
        if trunk_check:
            self.get_vehicle_state(trunk_check=True)
            
        if self.trunk_open:
            self.wake_up()
            try:
                res = self.api.actuate_trunk(which_trunk='rear')
            except (TeslaAPIError, TeslaCarOfflineError) as e:
                print(e)
                return
            
            if res['result'] == True:
                self.trunk_open = False
                print(f"{self.__class__.__name__}::Trunk closed")
            else:
                print(f"{self.__class__.__name__}::Failed to close trunk")    
        else:
            print(f"{self.__class__.__name__}::Trunk is already closed")


if __name__ == "__main__":

    try:
        from secrets import TESLA_AUTH_TOKEN, VEHICLE_TAG
    except ImportError:
        print("Error: Please create a secrets.py file with TESLA_AUTH_TOKEN and VEHICLE_TAG variables.")
        exit(1)

    my_tesla = TeslaCar(TESLA_AUTH_TOKEN, VEHICLE_TAG)

    if not my_tesla.trunk_open:    
        print('Opening trunk...')
        my_tesla.open_trunk()
        time.sleep(5)
        my_tesla.identify()
        time.sleep(5)
    
    if my_tesla.trunk_open:
        print('Closing trunk...')
        my_tesla.close_trunk()
        time.sleep(5)
        my_tesla.identify()
