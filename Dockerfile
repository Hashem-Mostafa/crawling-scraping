# Use official Python image
FROM mcr.microsoft.com/azure-functions/python:4-python3.10

# Enable V2 model layout
ENV AzureWebJobsScriptRoot=/home/site/wwwroot \
    AzureFunctionsJobHost__Logging__Console__IsEnabled=true

# Install Chrome dependencies
RUN apt-get update && apt-get install -y \
    wget unzip curl gnupg libglib2.0-0 libnss3 libgconf-2-4 libfontconfig1 libxss1 libappindicator1 libasound2 libatk-bridge2.0-0 libgtk-3-0

# Install Chrome
RUN curl -sSL https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb -o chrome.deb \
    && apt install -y ./chrome.deb \
    && rm chrome.deb

# Copy function code
COPY . /home/site/wwwroot
WORKDIR /home/site/wwwroot

# Install Python dependencies
RUN pip install --upgrade pip && pip install -r requirements.txt

# # During debugging, this entry point will be overridden. For more information, please refer to https://aka.ms/vscode-docker-python-debug
# CMD ["python", "function_app.py"]
