pipeline {
    agent { label 'media-workspace-agent' }
    parameters {
        booleanParam(name: 'DeployDemo', defaultValue: false, description: '发布通过测试的私有服务')
        booleanParam(name: 'DeployPublicDemo', defaultValue: false, description: '发布隔离的只读公开演示')
        choice(name: 'PublicDemoProvider', choices: ['mock', 'deepseek'], description: '新部署选 mock：服务器无 key，Web 手动临时 key')
    }
    options { timestamps(); disableConcurrentBuilds() }
    stages {
        stage('准备构建环境') {
            steps {
                sh 'mkdir -p reports'
                sh 'find reports -maxdepth 1 -type f -name "*.xml" -delete'
                sh 'sudo docker build --target prepared --tag ai-rag-platform:prepared-${BUILD_NUMBER} .'
            }
        }
        stage('检查模块依赖') {
            steps { sh 'sh scripts/run_ci_check.sh ai-rag-platform:prepared-${BUILD_NUMBER} scripts/check_module_dependencies.py' }
        }
        stage('测试一级模块源码') {
            steps { sh 'sh scripts/run_ci_check.sh ai-rag-platform:prepared-${BUILD_NUMBER} scripts/run_tests.py --mode source --group leaf --junitxml=reports/source-leaf.xml' }
        }
        stage('测试三个中间模块源码') {
            steps { sh 'sh scripts/run_ci_check.sh ai-rag-platform:prepared-${BUILD_NUMBER} scripts/run_tests.py --mode source --group facade --junitxml=reports/source-facade.xml' }
        }
        stage('测试模块装配和部署脚本') {
            steps { sh 'sh scripts/run_ci_check.sh ai-rag-platform:prepared-${BUILD_NUMBER} scripts/run_tests.py --mode source --group scripts --junitxml=reports/source-integration.xml' }
        }
        stage('编译模块并登记版本') {
            steps { sh 'sudo docker build --target compiled --tag ai-rag-platform:compiled-${BUILD_NUMBER} .' }
        }
        stage('测试一级模块编译产物') {
            steps { sh 'sh scripts/run_ci_check.sh ai-rag-platform:compiled-${BUILD_NUMBER} scripts/run_tests.py --mode binary --group leaf --junitxml=reports/binary-leaf.xml' }
        }
        stage('测试三个中间模块编译产物') {
            steps { sh 'sh scripts/run_ci_check.sh ai-rag-platform:compiled-${BUILD_NUMBER} scripts/run_tests.py --mode binary --group facade --junitxml=reports/binary-facade.xml' }
        }
        stage('核对接口并验证二进制来源') {
            steps {
                sh 'sh scripts/run_ci_check.sh ai-rag-platform:compiled-${BUILD_NUMBER} scripts/run_tests.py --mode binary --group specification --junitxml=reports/specification.xml'
                sh 'sh scripts/run_ci_check.sh ai-rag-platform:compiled-${BUILD_NUMBER} scripts/verify_compiled_runtime.py'
            }
        }
        stage('测试最终服务和网页') {
            steps { sh 'sh scripts/run_ci_check.sh ai-rag-platform:compiled-${BUILD_NUMBER} scripts/run_tests.py --mode binary --group app --junitxml=reports/app.xml' }
        }
        stage('用实例文档验证编译后检索') {
            steps { sh 'sh scripts/run_ci_check.sh ai-rag-platform:compiled-${BUILD_NUMBER} scripts/run_tests.py --mode binary --group scripts --junitxml=reports/binary-integration.xml' }
        }
        stage('用真实模型回答实例问题') {
            steps {
                withCredentials([string(credentialsId: 'rag-deepseek-api-key', variable: 'DEEPSEEK_API_KEY')]) {
                    sh '''
                        set +x
                        set -eu
                        umask 077
                        credential_file="$(mktemp)"
                        trap 'rm -f "$credential_file"' EXIT HUP INT TERM
                        printf 'DEEPSEEK_API_KEY=%s\n' "$DEEPSEEK_API_KEY" > "$credential_file"
                        CI_ENV_FILE="$credential_file" sh scripts/run_ci_check.sh "ai-rag-platform:compiled-${BUILD_NUMBER}" scripts/verify_live_model.py
                    '''
                }
            }
        }
        stage('打发布包并归档') {
            steps {
                sh 'sudo docker build --target builder --tag ai-rag-platform:ci-${BUILD_NUMBER} .'
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
        stage('发布私有服务') {
            when { expression { params.DeployDemo } }
            steps { sh 'BUILD_NUMBER="$BUILD_NUMBER" sh scripts/deploy_compose.sh' }
        }
        stage('发布只读公开演示') {
            when { expression { params.DeployPublicDemo } }
            steps { sh 'BUILD_NUMBER="$BUILD_NUMBER" PUBLIC_DEMO_PROVIDER="$PublicDemoProvider" sh scripts/deploy_public_demo.sh' }
        }
    }
    post {
        always { junit testResults: 'reports/*.xml', allowEmptyResults: true }
    }
}
