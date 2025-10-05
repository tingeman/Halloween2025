param (
    [Parameter(Position = 0, Mandatory = $true)]
    [string]$COM_PORT
)

# Get all .py files in the current directory
$files = Get-ChildItem -Filter *.py -File

foreach ($file in $files) {
    Write-Host "Processing file: $($file.Name)"

    # Remove the file from the ESP32 if it exists
    mpremote connect $COM_PORT fs rm $($file.Name) 2>$null

    # Copy the file to the ESP32
    mpremote connect $COM_PORT fs cp $($file.FullName) :
}

Write-Host "All .py files have been copied to the ESP32."