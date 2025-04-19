# Dockerfile
ARG PYTHON_VERSION=3.11
FROM python:${PYTHON_VERSION}-slim

LABEL maintainer="PatchMind Contributors"
LABEL description="Docker image for PatchMind IDE."

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    # Set backend for Qt to xcb
    QT_QPA_PLATFORM=xcb \
    # Often needed for Qt apps in Docker to avoid shared memory issues
    QT_X11_NO_MITSHM=1 \
    # Set Poetry path
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_CREATE="false" \
    # Add Poetry to PATH
    PATH="$POETRY_HOME/bin:$PATH"

# Install OS dependencies required for PyQt6/Qt6 GUI applications
# Includes X11 libs, fontconfig (for finding fonts), dbus, opengl
RUN apt-get update && apt-get install -y --no-install-recommends \
    libx11-6 \
    libxcb1 \
    libgl1 \
    libdbus-1-3 \
    libxkbcommon-x11-0 \
    libxcb-icccm4 \
    libxcb-image0 \
    libxcb-keysyms1 \
    libxcb-randr0 \
    libxcb-render-util0 \
    libxcb-shape0 \
    libxcb-sync1 \
    libxcb-xfixes0 \
    libxcb-xinerama0 \
    libxcb-xkb1 \
    fontconfig \
    libfreetype6 \
    # Install git just in case any dependency needs it during build
    git \
    && rm -rf /var/lib/apt/lists/*

# Install Poetry
RUN curl -sSL https://install.python-poetry.org | python3 -

# Set working directory
WORKDIR /app

# Copy dependency definition files
COPY pyproject.toml poetry.lock* ./

# Install project dependencies (excluding dev dependencies)
# Using --no-root because we copy the app code later
RUN poetry install --no-dev --no-interaction --no-ansi

# Copy the application code into the container
COPY . /app

# Default command is set in docker-compose.yml
# CMD ["python", "-m", "pm"]