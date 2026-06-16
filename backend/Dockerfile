# Stage 1: Base - Setup poetry environment variables and system dependencies
FROM python:3.12-slim AS base

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=off \
    PIP_DISABLE_PIP_VERSION_CHECK=on \
    PIP_DEFAULT_TIMEOUT=100 \
    POETRY_VERSION=1.8.3 \
    POETRY_HOME="/opt/poetry" \
    POETRY_VIRTUALENVS_IN_PROJECT=true \
    POETRY_NO_INTERACTION=1 \
    PYSETUP_PATH="/opt/pysetup" \
    VENV_PATH="/opt/pysetup/.venv"

# prepend poetry and venv to path
ENV PATH="$POETRY_HOME/bin:$VENV_PATH/bin:$PATH"

# Stage 2: Builder - Install build dependencies and build the virtualenv
FROM base AS builder
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        curl \
        build-essential \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# install poetry - respects $POETRY_VERSION & $POETRY_HOME
RUN curl -sSL https://install.python-poetry.org | python3 -

# copy project requirement files here to ensure they will be cached.
WORKDIR $PYSETUP_PATH
COPY pyproject.toml ./

# install runtime deps - uses $POETRY_VIRTUALENVS_IN_PROJECT=true and creates venv inside $PYSETUP_PATH
RUN poetry install --no-root --only main

# Stage 3: Development - Inherits from builder and installs dev dependencies
FROM builder AS development
WORKDIR $PYSETUP_PATH
RUN poetry install --no-root
WORKDIR /app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]

# Stage 4: Production - Lean and secure runtime image
FROM base AS production
RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        libpq5 \
    && rm -rf /var/lib/apt/lists/*

# copy in our built venv from builder
COPY --from=builder $PYSETUP_PATH $PYSETUP_PATH

# create a non-privileged user and set permissions
RUN addgroup --system app && adduser --system --group app
WORKDIR /app
COPY . /app
RUN chown -R app:app /app

USER app
EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
