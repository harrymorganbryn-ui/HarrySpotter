Harry Spotter for Linux (x86-64)
================================

GETTING STARTED
1. Extract this folder somewhere you can write to, e.g. your home folder:
       tar -xzf HarrySpotter-*-Linux-x86_64.tar.gz
   Keep all the files together - results are saved next to the program.
2. Run it:
       ./HarrySpotter
   Optional: ./install.sh adds Harry Spotter to your applications menu.

GOOGLE DRIVE
Google doesn't make a Drive app for Linux, so mount your Drive as a folder
with rclone (free) or Insync, then point Harry Spotter at it:
       sudo apt install rclone        (or your distribution's equivalent)
       rclone config                  (add a "Google Drive" remote, e.g. named gdrive)
       mkdir -p ~/GoogleDrive
       rclone mount gdrive: ~/GoogleDrive --daemon
~/GoogleDrive is found automatically; any other folder can be chosen in
Harry Spotter under Data -> Folders -> Google Drive folder.

YOU WILL NEED
- CCP4 (for Dimple and Coot), and Phenix for time-resolved Fo-Fo maps
- Coot 1 with working OpenGL graphics (normal desktops have this)
- PyMOL (optional, for "Open in PyMOL")
The Software card shows a tick for each one it finds; use Locate... if one
is installed somewhere unusual.

Tested on Ubuntu 22.04 and 24.04; other recent distributions should work.

PROBLEMS?
Send the Activity log text or results/pipeline_run.log.
