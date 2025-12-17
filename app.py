import os
import subprocess
import platform
from flask import Flask, render_template, request, send_file, flash
from werkzeug.utils import secure_filename

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
        'name': 'Prepress (Alta Qualidade)',
        'value': '/prepress',
        'description': 'Mantém alta qualidade para impressão profissional'
    },
    'ebook': {
        'name': 'E-book (Boa Qualidade)',
        'description': 'Equilíbrio entre qualidade e tamanho (recomendado)',
        'value': '/ebook'
    },
    'screen': {
        'name': 'Tela (Compressão Máxima)',
        'description': 'Tamanho mínimo para web - pode reduzir qualidade',
        'value': '/screen'
    }
}

def get_ghostscript_command():
    """Detecta automaticamente o comando Ghostscript baseado no sistema operacional"""
    # Caminhos fixos para tentar no Windows - AJUSTE SE NECESSÁRIO
    windows_paths = [
        r'C:\Program Files\gs\gs10.06.0\bin\gswin64c.exe',  # Caminho padrão 64-bit
        r'C:\Program Files (x86)\gs\gs10.06.0\bin\gswin32c.exe',  # Caminho padrão 32-bit
        'gswin64c.exe',  # Tenta pelo PATH do sistema
        'gswin32c.exe'
    ]
    
    for cmd in windows_paths:
        try:
            # Testa se o comando existe e pode ser executado
            result = subprocess.run([cmd, '--version'], 
                                  capture_output=True, 
                                  text=True,
                                  timeout=2)
            if result.returncode == 0:
                return cmd
        except (FileNotFoundError, OSError, subprocess.TimeoutExpired):
            continue
    
    return None

def compress_pdf(input_path, output_path, profile):
    """Compressa um PDF usando Ghostscript"""
    gs_command = get_ghostscript_command()
    
    if not gs_command:
        raise Exception("Ghostscript não encontrado. Por favor, instale-o.")
    
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
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            raise Exception(f"Erro no Ghostscript: {result.stderr}")
        return True
    except subprocess.TimeoutExpired:
        raise Exception("Tempo limite excedido ao comprimir o PDF")
    except Exception as e:
        raise Exception(f"Erro ao executar Ghostscript: {str(e)}")

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
            # Salva o arquivo original
            filename = secure_filename(file.filename)
            original_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
            file.save(original_path)
            
            # Obtém perfil de compressão
            profile_key = request.form.get('profile', 'ebook')
            profile = COMPRESSION_PROFILES[profile_key]['value']
            
            # Define caminhos
            base_name = os.path.splitext(filename)[0]
            compressed_filename = f"{base_name}_comprimido.pdf"
            compressed_path = os.path.join(app.config['COMPRESSED_FOLDER'], compressed_filename)
            
            try:
                # Verifica se Ghostscript está disponível
                gs_command = get_ghostscript_command()
                if not gs_command:
                    flash('Ghostscript não encontrado. Instale-o primeiro.', 'error')
                    return render_template('index.html', 
                                         profiles=COMPRESSION_PROFILES,
                                         ghostscript_installed=False)
                
                # Comprime o PDF
                compress_pdf(original_path, compressed_path, profile)
                
                # Obtém estatísticas
                original_size = os.path.getsize(original_path)
                compressed_size = os.path.getsize(compressed_path)
                reduction = ((original_size - compressed_size) / original_size) * 100
                
                # Prepara resultados
                results = {
                    'original_name': filename,
                    'original_size': f"{original_size / 1024:.2f} KB",
                    'compressed_name': compressed_filename,
                    'compressed_size': f"{compressed_size / 1024:.2f} KB",
                    'reduction': f"{reduction:.1f}%",
                    'profile_used': COMPRESSION_PROFILES[profile_key]['name']
                }
                
                flash('PDF comprimido com sucesso!', 'success')
                return render_template('index.html', 
                                     profiles=COMPRESSION_PROFILES,
                                     results=results,
                                     ghostscript_installed=True)
                
            except Exception as e:
                flash(f'Erro ao comprimir PDF: {str(e)}', 'error')
                # Remove arquivos temporários em caso de erro
                if os.path.exists(original_path):
                    os.remove(original_path)
                if os.path.exists(compressed_path):
                    os.remove(compressed_path)
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

@app.route('/download/<filename>')
def download_file(filename):
    """Permite baixar o arquivo comprimido"""
    return send_file(
        os.path.join(app.config['COMPRESSED_FOLDER'], filename),
        as_attachment=True,
        download_name=filename
    )

@app.route('/cleanup', methods=['POST'])
def cleanup():
    """Limpa os arquivos temporários"""
    import shutil
    try:
        # Remove todos os arquivos nas pastas de upload e compressed
        for folder in [app.config['UPLOAD_FOLDER'], app.config['COMPRESSED_FOLDER']]:
            for filename in os.listdir(folder):
                file_path = os.path.join(folder, filename)
                try:
                    if os.path.isfile(file_path):
                        os.unlink(file_path)
                except Exception as e:
                    print(f"Erro ao excluir {file_path}: {e}")
        
        flash('Arquivos temporários removidos com sucesso!', 'success')
    except Exception as e:
        flash(f'Erro ao limpar arquivos: {str(e)}', 'error')
    
    return render_template('index.html', 
                         profiles=COMPRESSION_PROFILES,
                         ghostscript_installed=bool(get_ghostscript_command()))

if __name__ == '__main__':
    app.run(host='0.0.0.0')