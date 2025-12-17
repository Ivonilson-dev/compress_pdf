import os
import subprocess
import platform
import time
import threading
from flask import Flask, render_template, request, send_file, flash, redirect, url_for, Response, jsonify
from werkzeug.utils import secure_filename
import json

app = Flask(__name__)
app.config['SECRET_KEY'] = 'sua_chave_secreta_aqui'
app.config['UPLOAD_FOLDER'] = 'uploads'
app.config['COMPRESSED_FOLDER'] = 'compressed'
app.config['MAX_CONTENT_LENGTH'] = 50 * 1024 * 1024  # 50MB max

# Criar pastas se não existirem
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
os.makedirs(app.config['COMPRESSED_FOLDER'], exist_ok=True)

# Configurações de compressão
COMPRESSION_PROFILES = {
    'prepress': {
        'name': 'Alta Qualidade',
        'value': '/prepress',
        'description': 'Mantém alta qualidade para impressão profissional'
    },
    'ebook': {
        'name': 'Boa Qualidade',
        'description': 'Equilíbrio entre qualidade e tamanho (recomendado)',
        'value': '/ebook'
    },
    'screen': {
        'name': 'Compressão Máxima',
        'description': 'Tamanho mínimo para web - pode reduzir qualidade',
        'value': '/screen'
    }
}

# Dicionário para armazenar progresso por sessão
progress_data = {}


def get_ghostscript_command():
    """Detecta automaticamente o comando Ghostscript."""
    sistema = platform.system()

    # Ordem de tentativas: Linux (gs) -> Windows (gswin64c)
    if sistema == "Linux":
        # No Linux, tenta apenas o comando padrão 'gs'
        comandos = ['gs']
    else:
        # Fallback para Windows (útil se testar localmente)
        comandos = ['gswin64c.exe', 'gswin32c.exe', 'gs.exe']

    for cmd in comandos:
        try:
            # Testa se o comando existe e funciona
            resultado = subprocess.run([cmd, '--version'],
                                       capture_output=True,
                                       text=True,
                                       timeout=5)
            if resultado.returncode == 0:
                # Retorna o caminho completo, se possível
                import shutil
                full_path = shutil.which(cmd) or cmd
                # Log útil
                print(f"[DEBUG] Ghostscript encontrado em: {full_path}")
                return full_path
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired) as e:
            print(f"[DEBUG] Comando '{cmd}' não encontrado: {e}")
            continue

    # Se nenhum comando funcionar
    raise Exception(
        "ERRO: Ghostscript não encontrado. Verifique se está instalado no sistema. O caminho esperado no Linux é 'gs'.")


def update_progress(session_id, stage, percentage, message=""):
    """Atualiza o progresso para uma sessão específica."""
    if session_id not in progress_data:
        progress_data[session_id] = {
            'stage': stage,
            'percentage': percentage,
            'message': message,
            'complete': False,
            'error': None,
            'result': None
        }
    else:
        progress_data[session_id]['stage'] = stage
        progress_data[session_id]['percentage'] = percentage
        progress_data[session_id]['message'] = message

    print(
        f"[PROGRESSO] Sessão {session_id}: {stage} - {percentage}% - {message}")


def compress_pdf_with_progress(input_path, output_path, profile, session_id):
    """Compressa um PDF usando Ghostscript com atualizações de progresso."""
    try:
        update_progress(session_id, "preparando", 10,
                        "Iniciando compressão...")

        gs_command = get_ghostscript_command()

        if not gs_command:
            raise Exception(
                "Ghostscript não encontrado. Por favor, instale-o.")

        # Comando Ghostscript
        cmd = [
            gs_command,
            '-sDEVICE=pdfwrite',
            '-dCompatibilityLevel=1.4',
            f'-dPDFSETTINGS={profile}',
            '-dNOPAUSE',
            '-dBATCH',
            '-dQUIET',
            f'-sOutputFile={output_path}',
            input_path
        ]

        update_progress(session_id, "processando", 30,
                        "Executando Ghostscript...")

        # Executa o comando Ghostscript
        result = subprocess.run(
            cmd, capture_output=True, text=True, timeout=30)

        if result.returncode != 0:
            raise Exception(f"Erro no Ghostscript: {result.stderr}")

        update_progress(session_id, "finalizando", 80,
                        "Calculando resultados...")

        # Obtém estatísticas
        original_size = os.path.getsize(input_path)
        compressed_size = os.path.getsize(output_path)
        reduction = ((original_size - compressed_size) /
                     original_size) * 100 if original_size > 0 else 0

        update_progress(session_id, "completo", 100, "Compressão concluída!")

        # Armazena o resultado
        progress_data[session_id]['complete'] = True
        progress_data[session_id]['result'] = {
            'original_size': original_size,
            'compressed_size': compressed_size,
            'reduction': reduction,
            'output_path': output_path,
            'output_filename': os.path.basename(output_path),
            'input_path': input_path,
            'input_filename': os.path.basename(input_path)
        }

        return True

    except subprocess.TimeoutExpired:
        error_msg = "Tempo limite excedido ao comprimir o PDF"
        progress_data[session_id]['error'] = error_msg
        progress_data[session_id]['complete'] = True
        raise Exception(error_msg)
    except Exception as e:
        error_msg = f"Erro ao executar Ghostscript: {str(e)}"
        progress_data[session_id]['error'] = error_msg
        progress_data[session_id]['complete'] = True
        raise Exception(error_msg)


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        # Verifica se um arquivo foi enviado
        if 'pdf_file' not in request.files:
            flash('Nenhum arquivo selecionado', 'error')
            return render_template('index.html', profiles=COMPRESSION_PROFILES)

        file = request.files['pdf_file']
        if file.filename == '':
            flash('Nenhum arquivo selecionado', 'error')
            return render_template('index.html', profiles=COMPRESSION_PROFILES)

        if file and file.filename.lower().endswith('.pdf'):
            # Gera um ID único para esta sessão de compressão
            import uuid
            session_id = str(uuid.uuid4())

            # Salva o arquivo original
            filename = secure_filename(file.filename)
            original_path = os.path.join(
                app.config['UPLOAD_FOLDER'], f"{session_id}_{filename}")
            file.save(original_path)

            # Obtém perfil de compressão
            profile_key = request.form.get('profile', 'ebook')
            profile = COMPRESSION_PROFILES[profile_key]['value']

            # Define caminhos
            base_name = os.path.splitext(filename)[0]
            compressed_filename = f"{session_id}_{base_name}_comprimido.pdf"
            compressed_path = os.path.join(
                app.config['COMPRESSED_FOLDER'], compressed_filename)

            # Verifica se Ghostscript está disponível
            try:
                gs_command = get_ghostscript_command()
                if not gs_command:
                    flash('Ghostscript não encontrado. Instale-o primeiro.', 'error')
                    return render_template('index.html',
                                           profiles=COMPRESSION_PROFILES,
                                           ghostscript_installed=False)

                # Inicia a compressão em uma thread separada
                def compress_thread():
                    try:
                        compress_pdf_with_progress(
                            original_path, compressed_path, profile, session_id)
                    except Exception as e:
                        print(f"Erro na thread de compressão: {e}")

                thread = threading.Thread(target=compress_thread)
                thread.daemon = True
                thread.start()

                # Redireciona para a página de progresso
                return redirect(url_for('compress_progress', session_id=session_id,
                                        original_name=filename, profile_name=COMPRESSION_PROFILES[profile_key]['name']))

            except Exception as e:
                flash(f'Erro ao iniciar compressão: {str(e)}', 'error')
                # Remove arquivos temporários em caso de erro
                if os.path.exists(original_path):
                    os.remove(original_path)
                return render_template('index.html',
                                       profiles=COMPRESSION_PROFILES,
                                       ghostscript_installed=bool(get_ghostscript_command()))

        else:
            flash('Por favor, selecione um arquivo PDF válido', 'error')

    # Verifica se Ghostscript está instalado
    gs_installed = bool(get_ghostscript_command())
    if not gs_installed:
        flash('Ghostscript não encontrado. Veja as instruções de instalação abaixo.', 'warning')

    return render_template('index.html',
                           profiles=COMPRESSION_PROFILES,
                           ghostscript_installed=gs_installed)


@app.route('/compress_progress/<session_id>')
def compress_progress(session_id):
    """Página que mostra o progresso da compressão."""
    original_name = request.args.get('original_name', 'arquivo.pdf')
    profile_name = request.args.get('profile_name', 'E-book')

    return render_template('progress.html',
                           session_id=session_id,
                           original_name=original_name,
                           profile_name=profile_name)


@app.route('/progress/<session_id>')
def get_progress(session_id):
    """Endpoint para obter o progresso atual da compressão."""
    if session_id in progress_data:
        data = progress_data[session_id]
        return jsonify({
            'stage': data['stage'],
            'percentage': data['percentage'],
            'message': data['message'],
            'complete': data['complete'],
            'error': data['error'],
            'result': data['result']
        })
    else:
        return jsonify({
            'stage': 'unknown',
            'percentage': 0,
            'message': 'Sessão não encontrada',
            'complete': True,
            'error': 'ID de sessão inválido'
        })


@app.route('/compress_result/<session_id>')
def compress_result(session_id):
    """Página de resultado final após a compressão."""
    if session_id not in progress_data or not progress_data[session_id]['complete']:
        flash('Resultado não disponível ou ainda processando', 'error')
        return redirect(url_for('index'))

    data = progress_data[session_id]

    if data['error']:
        flash(f'Erro na compressão: {data["error"]}', 'error')
        # Remove arquivos em caso de erro
        if data.get('result') and data['result'].get('input_path'):
            if os.path.exists(data['result']['input_path']):
                os.remove(data['result']['input_path'])
        return redirect(url_for('index'))

    if not data['result']:
        flash('Resultado não encontrado', 'error')
        return redirect(url_for('index'))

    result = data['result']

    # REMOVE O UUID para exibição amigável
    # O nome real do arquivo tem: "uuid_nome.pdf"
    # Para exibir: removemos a parte do uuid
    original_display_name = result['input_filename']
    compressed_display_name = result['output_filename']

    # Remove o UUID (parte antes do primeiro underscore)
    if '_' in original_display_name:
        original_display_name = original_display_name.split('_', 1)[1]
    if '_' in compressed_display_name:
        # Remove o UUID e troca "_comprimido" por " (comprimido)"
        temp_name = compressed_display_name.split('_', 1)[1]
        compressed_display_name = temp_name.replace(
            '_comprimido', '') + ' (comprimido).pdf'

    results = {
        'session_id': session_id,
        'original_name': original_display_name,
        'original_size': f"{result['original_size'] / 1024:.2f} KB",
        'compressed_name': compressed_display_name,  # Nome limpo para exibição
        # Nome real com UUID para download
        'real_compressed_filename': result['output_filename'],
        'compressed_size': f"{result['compressed_size'] / 1024:.2f} KB",
        'reduction': f"{result['reduction']:.1f}%",
        'profile_used': request.args.get('profile_name', 'E-book (Boa Qualidade)'),
        'input_path': result['input_path'],
        'output_path': result['output_path']
    }

    flash('PDF comprimido com sucesso!', 'success')
    return render_template('result.html',
                           results=results,
                           profiles=COMPRESSION_PROFILES,
                           ghostscript_installed=True)


@app.route('/download/<filename>')
def download_file(filename):
    """Permite baixar o arquivo comprimido"""
    file_path = os.path.join(app.config['COMPRESSED_FOLDER'], filename)

    # Verifica se o arquivo existe antes de tentar enviar
    if not os.path.exists(file_path):
        flash('Arquivo não encontrado. Pode ter sido excluído.', 'error')
        return redirect(url_for('index'))

    return send_file(
        file_path,
        as_attachment=True,
        download_name=filename.replace('_comprimido.pdf', '.pdf')
    )


@app.route('/cleanup/<session_id>', methods=['POST'])
def cleanup_session(session_id):
    """Limpa os arquivos temporários de uma sessão específica e redireciona para a página inicial."""
    try:
        # Verifica se temos informações sobre os arquivos desta sessão
        if session_id in progress_data:
            data = progress_data[session_id]

            # Remove arquivos específicos desta sessão
            if data.get('result'):
                # Remove arquivo original
                if 'input_path' in data['result'] and os.path.exists(data['result']['input_path']):
                    os.remove(data['result']['input_path'])
                    print(
                        f"Arquivo original removido: {data['result']['input_path']}")

                # Remove arquivo comprimido
                if 'output_path' in data['result'] and os.path.exists(data['result']['output_path']):
                    os.remove(data['result']['output_path'])
                    print(
                        f"Arquivo comprimido removido: {data['result']['output_path']}")

            # Remove os dados da sessão do dicionário
            del progress_data[session_id]

        flash('Arquivos temporários removidos com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao limpar arquivos: {str(e)}', 'error')
        print(f"Erro no cleanup: {e}")

    # SEMPRE redireciona para a página inicial
    return redirect(url_for('index'))


@app.route('/cleanup_all', methods=['POST'])
def cleanup_all():
    """Limpa TODOS os arquivos temporários (opção da página inicial)."""
    try:
        # Remove todos os arquivos nas pastas de upload e compressed
        for folder in [app.config['UPLOAD_FOLDER'], app.config['COMPRESSED_FOLDER']]:
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                        print(f"Arquivo removido: {file_path}")
                except Exception as e:
                    print(f"Erro ao excluir {file_path}: {e}")

        # Limpa todos os dados de progresso
        progress_data.clear()

        flash('Todos os arquivos temporários foram removidos com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao limpar arquivos: {str(e)}', 'error')

    # Redireciona para a página inicial
    return redirect(url_for('index'))


if __name__ == '__main__':
    app.run(host='0.0.0.0')
