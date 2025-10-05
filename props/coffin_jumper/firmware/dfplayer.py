import machine
import time

# DFPlayer Command Constants

DFP_CMD_VOL_UP = 0x04        # increase volume
DFP_CMD_VOL_DOWN = 0x05      # decrease volume
DFP_CMD_VOL = 0x06           # set volume (one argument)
DFP_CMD_RESET = 0x0C         # reset the module
DFP_CMD_RESUME = 0x0D        # resume playback
DFP_CMD_PAUSE = 0x0E         # pause playback
DFP_CMD_PLAY = 0x0F          # play a specific track in a specific folder (two arguments)
DFP_CMD_STOP = 0x16          # stop playback
DFP_CMD_IS_PLAYING = 0x42    # check if something is playing
DFP_CMD_GET_VOL = 0x43       # get current volume
DFP_CMD_GET_FILES = 0x4E     # get number of files in folder

class DFPlayer:
    def __init__(self,uart_id,tx_pin_id=None,rx_pin_id=None):
        self.uart_id=uart_id
        #init with given baudrate
        self.uart = machine.UART(uart_id, 9600)  
                
        #not all boards can set the pins for the uart channel
        if tx_pin_id or rx_pin_id:
            self.uart.init(9600, bits=8, parity=None, stop=1, tx=tx_pin_id, rx=rx_pin_id)
        else:
            self.uart.init(9600, bits=8, parity=None, stop=1)
        
    def flush(self):
        self.uart.flush()
        if self.uart.any():
            self.uart.read()
        
    def send_query(self,cmd,param1=0,param2=0):
        retry=True
        while (retry):
            self.flush()
            self.send_cmd(cmd,param1,param2)
            time.sleep(0.05)
            in_bytes = self.uart.read()
            if not in_bytes: #timeout
                return -1
            if len(in_bytes)==10 and in_bytes[1]==255 and in_bytes[9]==239:
                retry=False
        return in_bytes
    
    def send_cmd(self,cmd,param1=0,param2=0):
        out_bytes = bytearray(10)
        out_bytes[0]=126
        out_bytes[1]=255
        out_bytes[2]=6
        out_bytes[3]=cmd
        out_bytes[4]=0
        out_bytes[5]=param1
        out_bytes[6]=param2
        out_bytes[9]=239
        checksum = 0
        for i in range(1,7):
            checksum=checksum+out_bytes[i]
        out_bytes[7]=(checksum>>7)-1
        out_bytes[7]=~out_bytes[7]
        out_bytes[8]=checksum-1
        out_bytes[8]=~out_bytes[8]
        self.uart.write(out_bytes)

    def stop(self):
        self.send_cmd(DFP_CMD_STOP,0,0)

    def play(self,folder,file):
        self.stop()
        time.sleep(0.05)
        self.send_cmd(DFP_CMD_PLAY,folder,file)

    def pause(self):
        self.send_cmd(DFP_CMD_PAUSE, 0, 0)

    def resume(self):
        self.send_cmd(DFP_CMD_RESUME, 0, 0)
        
    def volume(self,vol):
        self.send_cmd(DFP_CMD_VOL,0,vol)
        
    def volume_up(self):
        self.send_cmd(DFP_CMD_VOL_UP,0,0)

    def volume_down(self):
        self.send_cmd(DFP_CMD_VOL_DOWN,0,0)
    
    def reset(self):
        self.send_cmd(DFP_CMD_RESET,0,1)
        
    def is_playing(self):
        in_bytes = self.send_query(DFP_CMD_IS_PLAYING)
        if in_bytes==-1 or in_bytes[5]!=2:
            return -1
        return in_bytes[6]
    
    def get_volume(self):
        in_bytes = self.send_query(DFP_CMD_GET_VOL)
        if in_bytes==-1 or in_bytes[3]!=DFP_CMD_GET_VOL:
            return -1
        return in_bytes[6]

    def get_files_in_folder(self,folder):
        in_bytes = self.send_query(DFP_CMD_GET_FILES,0,folder)
        if in_bytes==-1:
            return -1
        if in_bytes[3]!=DFP_CMD_GET_FILES:
            return 0
        return in_bytes[6]

