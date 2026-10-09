pipeline {
    agent { label 'media-workspace-agent' }
    parameters {
        booleanParam(
            name: 'DeployDemo',
            defaultValue: false,
            description: 'Deploy the tested image to the isolated ai-rag Compose service.'
        )
        booleanParam(
            name: 'DeployPublicDemo',
            defaultValue: false,
            description: 'Publish the isolated read-only interview demo after live candidate smoke.'
        )
        booleanParam(
            name: 'DeployAdminWorkspace',
            defaultValue: false,
            description: 'Deploy isolated owner login and guarded private notebook services after candidate import and Media auth smoke.'
        )
        choice(
            name: 'PublicDemoProvider',
            choices: ['deepseek', 'mock'],
            description: 'Explicit public provider; mock is an offline tool-flow demonstration.'
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
        stage('Deploy public interview demo') {
            when {
                expression { params.DeployPublicDemo }
            }
            steps {
                sh 'BUILD_NUMBER="$BUILD_NUMBER" PUBLIC_DEMO_PROVIDER="$PublicDemoProvider" sh scripts/deploy_public_demo.sh'
            }
        }
        stage('Deploy owner notebook workspace') {
            when {
                expression { params.DeployAdminWorkspace }
            }
            steps {
                sh 'BUILD_NUMBER="$BUILD_NUMBER" sh scripts/deploy_admin_workspace.sh'
            }
        }
    }
}
