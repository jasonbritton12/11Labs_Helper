# Headless engine image for cloud / SDVI Rally reuse.
# Build:  docker build -f packaging/Dockerfile -t elevenlabs-helper .
# Run:    docker run --rm -e ELEVENLABS_API_KEY=sk-... \
#             -v "$PWD/in:/in" -v "$PWD/out:/out" \
#             elevenlabs-helper transcribe /in/clip.mp3 --out /out
# V1 has no FFmpeg dependency (uploads the audio file as-is).
FROM python:3.12-slim

WORKDIR /app
COPY pyproject.toml /app/
COPY elevenlabs_helper /app/elevenlabs_helper

# Install the engine only (no GUI deps) so the image stays slim.
RUN pip install --no-cache-dir .

ENTRYPOINT ["elevenlabs-helper"]
CMD ["--help"]
