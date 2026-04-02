# Use the official Python 3.13 slim image for a smaller footprint
FROM python:3.13-slim

# Set the working directory inside the container
WORKDIR /code

# Copy only the requirements first to leverage Docker layer caching
COPY requirements.txt .

# Install the dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy the actual application code into the container
COPY ./app ./app

# Expose the port the FastAPI server will run on
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]