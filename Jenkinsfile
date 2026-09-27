pipeline {
    agent { label 'media-workspace-agent' }
    parameters {
        booleanParam(
            name: 'DeployDemo',
            defaultValue: true,
            description: 'Deploy the tested image to the isolated ai-rag Compose service.'
        )
    }
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
            when {
                expression { params.DeployDemo }
            }
            steps {
                sh 'BUILD_NUMBER="$BUILD_NUMBER" sh scripts/deploy_compose.sh'
            }
        }
    }
}
