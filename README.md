# Urbit<->Irc Bridge

## Instructions
1. git clone https://github.com/fitnub-bosbud/UrbitIrcBridge.git
2. pip3 install -r requirements.txt
3. Modify config.json to your liking 
    - Able to add multiple bots in the irc section for multiple servers
    - Able to add more channel groups
4. python3 irc_bridge.py

Looking at your url bar you can find the ship resource / channel name (respectively):
<img width="523" alt="image" src="https://user-images.githubusercontent.com/82548166/144684265-1fb45198-fba0-4130-870d-3dc340831a90.png">

This project was influenced by https://github.com/midsum-salrux/faux. I mirrored pretty close to their .json layout because it was a good way to pair channels.

