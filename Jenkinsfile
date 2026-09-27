pipeline {
    agent { label 'media-workspace-agent' }
    options {
        timestamps()
        disableConcurrentBuilds()
    }
    stages {
        stage('Build and test') {
            steps {
                sh 'sudo docker build --target builder --tag ai-rag-platform:ci-${BUILD_NUMBER} .'
            }
        }
        stage('Archive binary release') {
            steps {
                sh '''
                    set -eu
                    mkdir -p dist
                    cid="$(sudo docker create "ai-rag-platform:ci-${BUILD_NUMBER}")"
                    trap 'sudo docker rm -f "$cid" >/dev/null' EXIT
                    sudo docker cp "$cid:/opt/agent/dist/." dist/
                '''
                archiveArtifacts artifacts: 'dist/*.zip,dist/*.zip.sha256,dist/*.manifest.json', fingerprint: true
            }
        }
        stage('Deploy') {
            steps {
                sh '''
                    set -eu
                    sudo docker compose --project-name ai-rag up -d --build
                    cid="$(sudo docker compose --project-name ai-rag ps -q agent)"
                    test -n "$cid"
                    for attempt in $(seq 1 72); do
                        status="$(sudo docker inspect --format '{{.State.Health.Status}}' "$cid")"
                        if [ "$status" = healthy ]; then exit 0; fi
                        if [ "$status" = unhealthy ]; then
                            sudo docker compose --project-name ai-rag logs --tail=100 agent
                            exit 1
                        fi
                        sleep 5
                    done
                    sudo docker compose --project-name ai-rag logs --tail=100 agent
                    exit 1
                '''
            }
        }
    }
}
