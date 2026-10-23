import os

from dotenv import load_dotenv
from magic_hour import Client

load_dotenv()
key = os.getenv("MAGIC_HOUR_API_KEY")
if not key:
    raise SystemExit("MAGIC_HOUR_API_KEY is missing. Add it to .env first.")

client = Client(token=key)
r = client.v1.text_to_video.generate(
    end_seconds=5,
    aspect_ratio="16:9",
    style={"prompt": "a water droplet swelling and falling from a tap into a steel sink, "
                     "close-up, cinematic slow motion, soft daylight"},
    name="test",
    model="ltx-2.5",
    resolution="480p",
    wait_for_completion=True,
    download_outputs=True,
    download_directory=".",
)
print(r.status, r.downloaded_paths, r.credits_charged)
if r.status != "complete" and getattr(r, "error", None):
    print("Error:", r.error.message)