pipeline {
    agent {
        label 'inferrence1 || aitop'
    }

    environment {
        // Minimum environmental variable pointing to your server.
        // Users can login via the frontend dashboard to supply the remaining credentials.
        JOPLIN_SERVER_URL = 'https://joplin.adamoutler.com'
    }

    stages {
        stage('Checkout & Update') {
            steps {
                // As requested: Expecting the code to be on the node, just pull the latest changes.
                // (Note: If Jenkins manages the workspace cleanly, `checkout scm` is standard, 
                // but we are using `git pull` here based on your workflow expectation).
                sh 'git pull'
            }
        }

        stage('Buildx') {
            steps {
                // Generate a minimal .env file so docker-compose picks up the server URL
                // and doesn't complain about missing variables.
                sh 'echo "JOPLIN_SERVER_URL=${JOPLIN_SERVER_URL}" > .env'
                
                // Build the images (docker compose uses buildx by default in modern versions)
                sh 'docker compose build'
            }
        }

        stage('Deploy') {
            steps {
                // Recreate the containers and run in detached mode
                sh 'docker compose up -d --force-recreate'
            }
        }
    }
}
