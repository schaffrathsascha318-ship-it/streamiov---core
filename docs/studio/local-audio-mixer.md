# STREAMIOV Studio local audio mixer

The Studio now has a Web Audio mixer engine that accepts live MediaStream audio inputs, applies independent gain/mute controls, and combines them into one MediaStreamAudioDestinationNode output.

Current integration:
- The actual local microphone capture is routed into the mixer.
- The microphone fader controls its gain (0–100%).
- Stopping microphone capture disconnects the mixer input; closing the window closes the audio graph.
- The mixer can accept additional named streams (music, game, TTS and alerts) through its channel API.

Important boundary:
- The mixed output stream is prepared for a future encoder adapter but is not yet consumed by GStreamer or an RTMP output.
- Music/game/TTS/alerts are not yet connected as live inputs.
- No audio is transmitted and this does not indicate LIVE.
- TikTok OAuth and token handling are untouched.

Run npm run test:engine.
