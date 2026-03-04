# mmmmhh

`mmmmhh` is a simple app to make spoken videos tighter and cleaner.

It can:
- remove long silences
- keep natural pacing
- add subtitles
- export a final video

## Open the app

```bash
npm run setup:mac
.venv/bin/python3 app.py
```

## How to use
1. Choose your video.
2. Choose where to save the result.
3. Click **Process**.

Optional:
- turn subtitles on/off
- save a transcript
- preview/edit subtitle text before export

Output:
- final video (`.mp4`)
- subtitles (`.srt`, optional)
- transcript (`.txt`, optional)
