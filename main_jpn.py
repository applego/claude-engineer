import os
from dotenv import load_dotenv
import json
from tavily import TavilyClient
import base64
from PIL import Image
import io
import re
from anthropic import Anthropic, APIStatusError, APIError
import difflib
import time
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.markdown import Markdown
import asyncio
import aiohttp
from prompt_toolkit import PromptSession
from prompt_toolkit.styles import Style


async def get_user_input(prompt="あなた: "):
    style = Style.from_dict(
        {
            "prompt": "cyan bold",
        }
    )
    session = PromptSession(style=style)
    return await session.prompt_async(prompt, multiline=False)


from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn
import datetime
import venv
import subprocess
import sys
import signal
import logging
from typing import Tuple, Optional


def setup_virtual_environment() -> Tuple[str, str]:
    """
    コード実行環境用の仮想環境を設定します。

    Returns:
        Tuple[str, str]: 仮想環境のパスとアクティベートスクリプトのパス
    """
    venv_name = "code_execution_env"
    venv_path = os.path.join(os.getcwd(), venv_name)
    try:
        if not os.path.exists(venv_path):
            venv.create(venv_path, with_pip=True)

        # 仮想環境をアクティベートする
        if sys.platform == "win32":
            activate_script = os.path.join(venv_path, "Scripts", "activate.bat")
        else:
            activate_script = os.path.join(venv_path, "bin", "activate")

        return venv_path, activate_script
    except Exception as e:
        logging.error(f"仮想環境の設定中にエラーが発生しました: {str(e)}")
        raise


# .envファイルから環境変数をロードする
load_dotenv()

# Anthropicクライアントを初期化する
anthropic_api_key = os.getenv("ANTHROPIC_API_KEY")
if not anthropic_api_key:
    raise ValueError("環境変数にANTHROPIC_API_KEYが見つかりません")
client = Anthropic(api_key=anthropic_api_key)

# Tavilyクライアントを初期化する
tavily_api_key = os.getenv("TAVILY_API_KEY")
if not tavily_api_key:
    raise ValueError("環境変数にTAVILY_API_KEYが見つかりません")
tavily = TavilyClient(api_key=tavily_api_key)

console = Console()


# トークン追跡変数
main_model_tokens = {"input": 0, "output": 0}
tool_checker_tokens = {"input": 0, "output": 0}
code_editor_tokens = {"input": 0, "output": 0}
code_execution_tokens = {"input": 0, "output": 0}

# 会話メモリを設定する（MAINMODELのコンテキストを維持する）
conversation_history = []

# ファイルの内容を格納する（MAINMODELのコンテキストの一部）
file_contents = {}

# コードエディタのメモリ（CODEEDITORMODELの呼び出し間でいくつかのコンテキストを維持する）
code_editor_memory = []

# コードエディタのコンテキストに既に存在するファイル
code_editor_files = set()

# 自動モードフラグ
automode = False

# ファイルの内容を格納する
file_contents = {}

# 実行中のプロセスを格納するグローバル辞書
running_processes = {}

# 定数
CONTINUATION_EXIT_PHRASE = "AUTOMODE_COMPLETE"  # 自動モード完了フレーズ
MAX_CONTINUATION_ITERATIONS = 25  # 最大継続反復回数
MAX_CONTEXT_TOKENS = 200000  # コンテキストウィンドウ用に20万トークンに削減

# モデル
# 対話間でコンテキストメモリを維持するモデル
MAINMODEL = "claude-3-5-sonnet-20240620"  # 会話履歴とファイルの内容を維持する

# コンテキストを維持しないモデル（呼び出しごとにメモリがリセットされる）
TOOLCHECKERMODEL = "claude-3-5-sonnet-20240620"
CODEEDITORMODEL = "claude-3-5-sonnet-20240620"
CODEEXECUTIONMODEL = "claude-3-5-sonnet-20240620"

# システムプロンプト
BASE_SYSTEM_PROMPT = """
あなたは、AnthropicのClaude-3.5-Sonnetモデルを搭載したAIアシスタントClaudeで、さまざまなツールにアクセスでき、コーディングエージェントとコード実行エージェントに指示と指示を与えることができるソフトウェア開発に特化しています。あなたの能力には以下が含まれます。

1. プロジェクト構造の作成と管理
2. 複数の言語にわたるコードの記述、デバッグ、改善
3. アーキテクチャの洞察を提供し、設計パターンを適用する
4. 最新のテクノロジーとベストプラクティスを常に把握する
5. プロジェクトディレクトリ内のファイルの分析と操作
6. 最新情報を得るためのウェブ検索の実行
7. 分離された「code_execution_env」仮想環境内でコードを実行し、その出力を分析する
8. 「code_execution_env」内で開始された実行中のプロセスの管理と停止

利用可能なツールとその最適なユースケース：

1. create_folder: プロジェクト構造に新しいディレクトリを作成します。
2. create_file: 指定された内容で新しいファイルを生成します。できるだけ完全で役立つファイルを作成するように努めてください。
3. edit_and_apply: 別のAIコーディングエージェントに指示することによって、既存のファイルを調べて変更します。あなたはこのエージェントに明確で詳細な指示を提供する責任があります。このツールを使用する場合は、次の点に注意してください。
   - 最近の変更、新しい変数や関数、ファイルの相互接続方法など、プロジェクトに関する包括的なコンテキストを提供します。
   - 必要な特定の変更または改善点を明確に述べ、各変更の背後にある理由を説明します。
   - 変更するコードのすべてのスニペットを、希望する変更とともに含めます。
   - 従うべきコーディング標準、命名規則、またはアーキテクチャパターンを指定します。
   - 変更によって発生する可能性のある問題や競合を予測し、それらを処理する方法についてガイダンスを提供します。
4. execute_code: 「code_execution_env」仮想環境内でのみPythonコードを実行し、その出力を分析します。コードの機能をテストしたり、問題を診断したりする必要がある場合に使用します。すべてのコード実行はこの分離された環境で行われることに注意してください。このツールは、長時間実行されるプロセスのプロセスIDを返すようになりました。
5. stop_process: IDによって実行中のプロセスを停止します。execute_codeツールによって開始された長時間実行されるプロセスを終了する必要がある場合に使用します。
6. read_file: 既存のファイルの内容を読み取ります。
7. read_multiple_files: 複数の既存のファイルの内容を一度に読み取ります。複数のファイルを同時に調べて操作する必要がある場合に使用します。
8. list_files: 指定されたフォルダ内のすべてのファイルとディレクトリを一覧表示します。
9. tavily_search: 最新情報を得るためにTavily APIを使用してウェブ検索を実行します。

ツールの使用ガイドライン：
- 常に手元のタスクに最適なツールを使用してください。
- ツールを使用する場合は、特にedit_and_applyの場合は、詳細で明確な指示を提供してください。
- 変更を加えた後、常に出力を確認して、正確性と意図との整合性を確保してください。
- execute_codeを使用して「code_execution_env」仮想環境内でコードを実行してテストし、結果を分析します。
- 長時間実行されるプロセスについては、execute_codeによって返されたプロセスIDを使用して、後で必要に応じて停止します。
- 最新情報や追加のコンテキストが必要な場合は、積極的にtavily_searchを使用してください。
- 複数のファイルを操作する場合は、効率のためにread_multiple_filesの使用を検討してください。

エラー処理とリカバリ：
- ツールの操作が失敗した場合は、エラーメッセージを注意深く分析し、問題の解決を試みてください。
- ファイル関連のエラーの場合は、再試行する前にファイルパスと権限を再確認してください。
- 検索が失敗した場合は、クエリの言い回しを変えたり、より小さく、より具体的な検索に分割してみてください。
- コードの実行が失敗した場合は、環境の分離された性質を考慮して、エラー出力を分析し、潜在的な修正を提案してください。
- プロセスの停止に失敗した場合は、潜在的な理由を検討し、代替アプローチを提案してください。

プロジェクトの作成と管理：
1. まず、新しいプロジェクトのルートフォルダを作成します。
2. ルートフォルダ内に必要なサブディレクトリとファイルを作成します。
3. 特定のプロジェクトタイプのベストプラクティスに従って、プロジェクト構造を論理的に編成します。

常に、応答と行動の正確性、明確さ、効率性を心がけてください。指示は正確かつ包括的でなければなりません。不確実な場合は、tavily_searchツールを使用するか、制限事項を認めてください。コードを実行する場合は、常に分離された「code_execution_env」仮想環境で実行されることを忘れないでください。開始した長時間実行されるプロセスを認識し、必要なくなったときに停止するなど、適切に管理してください。

ツールを使用する場合は、次の点に注意してください。
1. ツールを使用する前に、ツールが必要かどうかを慎重に検討してください。
2. 必要なすべてのパラメータが提供され、有効であることを確認してください。
3. 成功した結果とエラーの両方を適切に処理してください。
4. ツールの使用と結果をユーザーに明確に説明してください。

あなたはAIアシスタントであり、あなたの主な目標は、開発環境の整合性とセキュリティを維持しながら、ユーザーがタスクを効果的かつ効率的に達成するのを支援することであることを忘れないでください。
"""

AUTOMODE_SYSTEM_PROMPT = """
あなたは現在、自動モードになっています。次のガイドラインに従ってください。

1. 目標設定：
   - ユーザーのリクエストに基づいて、明確で達成可能な目標を設定します。
   - 複雑なタスクを、小さく管理しやすい目標に分割します。

2. 目標実行：
   - 各タスクに適切なツールを使用して、体系的に目標を達成します。
   - 必要に応じて、ファイル操作、コードの記述、ウェブ検索を利用します。
   - 編集する前に必ずファイルを読み取り、編集後に変更を確認します。

3. 進捗状況の追跡：
   - 目標の達成と全体的な進捗状況について定期的に更新を提供します。
   - 反復情報を使用して、作業のペースを効果的に調整します。

4. ツールの使用：
   - 目標を効率的に達成するために、利用可能なすべてのツールを活用します。
   - ファイルの変更にはedit_and_applyを優先し、大規模な編集の場合はチャンクで変更を適用します。
   - 最新情報を得るために、積極的にtavily_searchを使用します。

5. エラー処理：
   - ツールの操作が失敗した場合は、エラーを分析し、問題の解決を試みてください。
   - 永続的なエラーの場合は、目標を達成するための代替アプローチを検討してください。

6. 自動モードの完了：
   - すべての目標が達成されたら、「AUTOMODE_COMPLETE」と応答して自動モードを終了します。
   - 目標が達成されたら、追加のタスクや変更を要求しないでください。

7. 反復の認識：
   - あなたはこの{iteration_info}にアクセスできます。
   - この情報を使用して、タスクの優先順位付けと時間の効果的な管理を行います。

忘れないでください：確立された目標を効率的かつ効果的に完了することに焦点を当ててください。不要な会話や追加のタスクの要求は避けてください。
"""


def update_system_prompt(
    current_iteration: Optional[int] = None, max_iterations: Optional[int] = None
) -> str:
    """
    現在のコンテキストに基づいてシステムプロンプトを更新します。

    Args:
        current_iteration (Optional[int], optional): 現在の自動モードの反復回数。デフォルトはNone。
        max_iterations (Optional[int], optional): 自動モードの最大反復回数。デフォルトはNone。

    Returns:
        str: 更新されたシステムプロンプト
    """
    global file_contents
    chain_of_thought_prompt = """
    関連するツール（利用可能な場合）を使用して、ユーザーのリクエストに回答します。ツールを呼び出す前に、<thinking></thinking>タグ内で分析を行います。まず、提供されたツールのうち、ユーザーのリクエストに回答するのに関連するツールを検討します。次に、関連するツールの必要なパラメータをそれぞれ確認し、ユーザーが値を直接提供しているか、値を推測するのに十分な情報を提供しているかを判断します。パラメータを推測できるかどうかを判断する際には、すべてのコンテキストを注意深く検討して、特定の値がサポートされているかどうかを確認します。必要なパラメータがすべて存在するか、合理的に推測できる場合は、思考タグを閉じ、ツール呼び出しに進みます。ただし、必須パラメータの値のいずれかが欠落している場合は、関数呼び出しを行わず（欠落しているパラメータのプレースホルダーを使用する場合でも）、代わりにユーザーに欠落しているパラメータを提供するように求めます。オプションのパラメータの情報が提供されていない場合は、詳細情報を求めません。

    返された検索結果の品質について、回答に反映しないでください。
    """

    file_contents_prompt = "\n\nファイルの内容:\n"
    for path, content in file_contents.items():
        file_contents_prompt += f"\n--- {path} ---\n{content}\n"

    if automode:
        iteration_info = ""
        if current_iteration is not None and max_iterations is not None:
            iteration_info = f"あなたは現在、自動モードの{max_iterations}回の反復のうち、{current_iteration}回目を実行しています。"
        return (
            BASE_SYSTEM_PROMPT
            + file_contents_prompt
            + "\n\n"
            + AUTOMODE_SYSTEM_PROMPT.format(iteration_info=iteration_info)
            + "\n\n"
            + chain_of_thought_prompt
        )
    else:
        return (
            BASE_SYSTEM_PROMPT + file_contents_prompt + "\n\n" + chain_of_thought_prompt
        )


def create_folder(path):
    """
    指定されたパスに新しいフォルダを作成します。

    Args:
        path (str): フォルダを作成する絶対パスまたは相対パス。Windowsシステムでもパス区切りにはスラッシュ（/）を使用します。

    Returns:
        str: フォルダが作成された場合は成功メッセージ、問題が発生した場合はエラーメッセージ
    """
    try:
        os.makedirs(path, exist_ok=True)
        return f"フォルダが作成されました: {path}"
    except Exception as e:
        return f"フォルダの作成中にエラーが発生しました: {str(e)}"


def create_file(path, content=""):
    """
    指定されたパスに、指定された内容で新しいファイルを作成します。

    Args:
        path (str): ファイルを作成する絶対パスまたは相対パス。Windowsシステムでもパス区切りにはスラッシュ（/）を使用します。
        content (str, optional): ファイルの内容。必要なコード、コメント、フォーマットを含める必要があります。デフォルトは空の文字列です。

    Returns:
        str: ファイルが作成された場合は成功メッセージ、問題が発生した場合はエラーメッセージ
    """
    global file_contents
    try:
        with open(path, "w") as f:
            f.write(content)
        file_contents[path] = content
        return f"ファイルが作成され、システムプロンプトに追加されました: {path}"
    except Exception as e:
        return f"ファイルの作成中にエラーが発生しました: {str(e)}"


def highlight_diff(diff_text):
    """
    diffテキストをハイライト表示します。

    Args:
        diff_text (str): ハイライト表示するdiffテキスト

    Returns:
        Syntax: ハイライト表示されたdiffテキスト
    """
    return Syntax(diff_text, "diff", theme="monokai", line_numbers=True)


async def generate_edit_instructions(
    file_path, file_content, instructions, project_context, full_file_contents
):
    """
    コードファイルの編集指示を生成します。

    Args:
        file_path (str): 編集するファイルの絶対パスまたは相対パス。
        file_content (str): ファイルの現在の内容。
        instructions (str): ファイルに加える変更に関する指示。
        project_context (str): プロジェクトに関する追加のコンテキスト。
        full_file_contents (dict): すべてのファイルの内容を含む辞書。

    Returns:
        list: 生成された編集指示のリスト
    """
    global code_editor_tokens, code_editor_memory, code_editor_files
    try:
        # メモリコンテキストを準備する（これは呼び出し間でいくつかのコンテキストを維持する唯一の部分です）
        memory_context = "\n".join(
            [f"メモリ {i+1}:\n{mem}" for i, mem in enumerate(code_editor_memory)]
        )

        # 完全なファイルの内容コンテキストを準備する。編集中のファイルが既にcode_editor_filesにある場合は除外する。
        full_file_contents_context = "\n\n".join(
            [
                f"--- {path} ---\n{content}"
                for path, content in full_file_contents.items()
                if path != file_path or path not in code_editor_files
            ]
        )

        system_prompt = f"""
        あなたは、コードファイルの編集指示を生成するAIコーディングエージェントです。あなたの仕事は、提供されたコードを分析し、必要な変更のためのSEARCH/REPLACEブロックを生成することです。次の手順に従ってください。

        1. コンテキストを理解するためにファイルの内容全体を確認します。
        {file_content}

        2. 特定の指示を注意深く分析します。
        {instructions}

        3. プロジェクト全体のコンテキストを考慮します。
        {project_context}

        4. 以前の編集のメモリを考慮します。
        {memory_context}

        5. プロジェクト内のすべてのファイルの完全なコンテキストを考慮します。
        {full_file_contents_context}

        6. 必要な変更ごとにSEARCH/REPLACEブロックを生成します。各ブロックには、次のものが含まれている必要があります。
           - 変更するコードを一意に識別するのに十分なコンテキスト
           - 正しいインデントとフォーマットを維持した正確な置換コード
           - 大規模な変更ではなく、特定のターゲットを絞った変更に焦点を当てる

        7. SEARCH/REPLACEブロックが次のことを確認します。
           - 指示のすべての関連する側面に対処する
           - コードの可読性と効率性を維持または向上させる
           - コードの全体的な構造と目的を考慮する
           - 言語のベストプラクティスとコーディング標準に従う
           - プロジェクトのコンテキストと以前の編集との整合性を維持する
           - プロジェクト内のすべてのファイルの完全なコンテキストを考慮する

        重要：SEARCH/REPLACEブロックのみを返します。説明やコメントは含めないでください。
        各ブロックには、次のフォーマットを使用してください。

        <SEARCH>
        置き換えられるコード
        </SEARCH>
        <REPLACE>
        挿入する新しいコード
        </REPLACE>

        変更が必要ない場合は、空のリストを返します。
        """

        # CODEEDITORMODELへのAPI呼び出しを行う（code_editor_memoryを除き、コンテキストは維持されません）
        response = client.messages.create(
            model=CODEEDITORMODEL,
            max_tokens=8000,
            system=system_prompt,
            extra_headers={"anthropic-beta": "max-tokens-3-5-sonnet-2024-07-15"},
            messages=[
                {
                    "role": "user",
                    "content": "必要な変更のためのSEARCH/REPLACEブロックを生成します。",
                }
            ],
        )
        # コードエディタのトークン使用量を更新する
        code_editor_tokens["input"] += response.usage.input_tokens
        code_editor_tokens["output"] += response.usage.output_tokens

        # SEARCH/REPLACEブロックを抽出するために応答を解析する
        edit_instructions = parse_search_replace_blocks(response.content[0].text)

        # コードエディタのメモリを更新する（これは呼び出し間でいくつかのコンテキストを維持する唯一の部分です）
        code_editor_memory.append(f"{file_path}の編集指示:\n{response.content[0].text}")

        # code_editor_filesセットにファイルを追加する
        code_editor_files.add(file_path)

        return edit_instructions

    except Exception as e:
        console.print(
            f"編集指示の生成中にエラーが発生しました: {str(e)}", style="bold red"
        )
        return []  # 例外が発生した場合は空のリストを返す


def parse_search_replace_blocks(response_text):
    """
    応答テキストからSEARCH/REPLACEブロックを解析します。

    Args:
        response_text (str): 解析する応答テキスト

    Returns:
        str: 解析されたSEARCH/REPLACEブロックを含むJSON文字列
    """
    blocks = []
    pattern = r"<SEARCH>\n(.*?)\n</SEARCH>\n<REPLACE>\n(.*?)\n</REPLACE>"
    matches = re.findall(pattern, response_text, re.DOTALL)

    for search, replace in matches:
        blocks.append({"search": search.strip(), "replace": replace.strip()})

    return json.dumps(blocks)  # JSON文字列を返し続ける


async def edit_and_apply(
    path, instructions, project_context, is_automode=False, max_retries=3
):
    """
        特定の指示と詳細なプロジェクトコンテキストに基づいて、ファイルにAIを活用した改善を適用します。
        この関数は、ファイルを読み取り、会話履歴と包括的なコード関連プロジェクトコンテキストを使用して、AIでバッチ処理を行います。
        diffを生成し、ユーザーが変更を適用する前に確認できるようにします。
        目標は、一貫性を維持し、ファイル間の接続が壊れないようにすることです。
        このツールは、より広範なプロジェクトコンテキストを理解する必要がある複雑なコード変更に使用してください。

        Args:
            path (str): 編集するファイルの絶対パスまたは相対パス。Windowsシステムでもパス区切りにはスラッシュ（/）を使用します。
            instructions (str): コードレビューの完了後、<PLANNING>タグの間に変更の計画を立てます。関連する可能性のある追加のソースファイルまたはドキュメントを要求します。計画は重複を避ける必要があり（DRY原則）、保守性と柔軟性のバランスを取る必要があります。このステップでは、トレードオフと実装の選択肢を提示します。利用可能なフレームワークとライブラリを検討し、関連する場合にはそれらの使用を提案します。計画に同意していない場合は、このステップで停止します。

    同意したら、<OUTPUT>タグの間にコードを生成します。変数名、識別子、文字列リテラルに注意し、特に指示がない限り、元のソースファイルから正確に再現されていることを確認します。慣例に従って命名する場合は、二重コロンで囲み、::UPPERCASE::で囲みます。既存のコードスタイルを維持し、言語に適したイディオムを使用します。最初のバックティックの後に指定された言語でコードブロックを生成します。
            project_context (str): 最近の変更、新しい変数や関数、ファイル間の相互接続、コーディング標準、編集に影響を与える可能性のあるその他の関連情報など、プロジェクトに関する包括的なコンテキスト。
            is_automode (bool, optional): 自動モードで動作しているかどうかを示します。デフォルトはFalseです。
            max_retries (int, optional): 編集の適用を試行する最大回数。デフォルトは3です。

        Returns:
            str: 変更が適用された場合は成功メッセージ、問題が発生した場合はエラーメッセージ
    """
    global file_contents
    try:
        original_content = file_contents.get(path, "")
        if not original_content:
            with open(path, "r") as file:
                original_content = file.read()
            file_contents[path] = original_content

        for attempt in range(max_retries):
            edit_instructions_json = await generate_edit_instructions(
                path, original_content, instructions, project_context, file_contents
            )

            if edit_instructions_json:
                edit_instructions = json.loads(
                    edit_instructions_json
                )  # ここでJSONを解析する
                console.print(
                    Panel(
                        f"試行 {attempt + 1}/{max_retries}: 次のSEARCH/REPLACEブロックが生成されました:",
                        title="編集指示",
                        style="cyan",
                    )
                )
                for i, block in enumerate(edit_instructions, 1):
                    console.print(f"ブロック {i}:")
                    console.print(
                        Panel(
                            f"検索:\n{block['search']}\n\n置換:\n{block['replace']}",
                            expand=False,
                        )
                    )

                edited_content, changes_made, failed_edits = await apply_edits(
                    path, edit_instructions, original_content
                )

                if changes_made:
                    file_contents[path] = (
                        edited_content  # ファイルの内容を新しい内容で更新する
                    )
                    console.print(
                        Panel(
                            f"システムプロンプト内のファイルの内容が更新されました: {path}",
                            style="green",
                        )
                    )

                    if failed_edits:
                        console.print(
                            Panel(
                                f"一部の編集を適用できませんでした。再試行しています...",
                                style="yellow",
                            )
                        )
                        instructions += f"\n\n適用できなかった次の編集を再試行してください:\n{failed_edits}"
                        original_content = edited_content
                        continue

                    return f"{path}に変更が適用されました"
                elif attempt == max_retries - 1:
                    return f"{max_retries}回試行した後も、{path}に変更を適用できませんでした。編集指示を確認して、もう一度試してください。"
                else:
                    console.print(
                        Panel(
                            f"試行{attempt + 1}では変更を適用できませんでした。再試行しています...",
                            style="yellow",
                        )
                    )
            else:
                return f"{path}の変更は提案されませんでした"

        return f"{max_retries}回試行した後も、{path}に変更を適用できませんでした。"
    except Exception as e:
        return f"ファイルの編集/適用中にエラーが発生しました: {str(e)}"


async def apply_edits(file_path, edit_instructions, original_content):
    """
    生成された編集指示をファイルに適用します。

    Args:
        file_path (str): 編集するファイルのパス。
        edit_instructions (list): 適用する編集指示のリスト。
        original_content (str): ファイルの元の内容。

    Returns:
        tuple: 編集されたコンテンツ、変更が行われたかどうかを示すブール値、失敗した編集のリスト
    """
    changes_made = False
    edited_content = original_content
    total_edits = len(edit_instructions)
    failed_edits = []

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("[progress.percentage]{task.percentage:>3.0f}%"),
        console=console,
    ) as progress:
        edit_task = progress.add_task(
            "[cyan]編集を適用しています...", total=total_edits
        )

        for i, edit in enumerate(edit_instructions, 1):
            search_content = edit["search"].strip()
            replace_content = edit["replace"].strip()

            # 先頭/末尾の空白を無視してコンテンツを見つけるために正規表現を使用する
            pattern = re.compile(re.escape(search_content), re.DOTALL)
            match = pattern.search(edited_content)

            if match:
                # 元の空白を保持してコンテンツを置き換える
                start, end = match.span()
                # replace_contentから<SEARCH>と<REPLACE>タグを削除する
                replace_content_cleaned = re.sub(
                    r"</?SEARCH>|</?REPLACE>", "", replace_content
                )
                edited_content = (
                    edited_content[:start]
                    + replace_content_cleaned
                    + edited_content[end:]
                )
                changes_made = True

                # この編集の差分を表示する
                diff_result = generate_diff(search_content, replace_content, file_path)
                console.print(
                    Panel(
                        diff_result,
                        title=f"{file_path}の変更 ({i}/{total_edits})",
                        style="cyan",
                    )
                )
            else:
                console.print(
                    Panel(
                        f"編集 {i}/{total_edits} は適用されませんでした: コンテンツが見つかりません",
                        style="yellow",
                    )
                )
                failed_edits.append(f"編集 {i}: {search_content}")

            progress.update(edit_task, advance=1)

    if not changes_made:
        console.print(
            Panel(
                "変更は適用されませんでした。ファイルの内容は既に目的の状態と一致しています。",
                style="green",
            )
        )
    else:
        # 変更をファイルに書き込む
        with open(file_path, "w") as file:
            file.write(edited_content)
        console.print(Panel(f"変更が{file_path}に書き込まれました", style="green"))

    return edited_content, changes_made, "\n".join(failed_edits)


def generate_diff(original, new, path):
    """
    2つの文字列間の差分を生成します。

    Args:
        original (str): 元の文字列。
        new (str): 新しい文字列。
        path (str): ファイルのパス。

    Returns:
        Syntax: ハイライト表示された差分オブジェクト
    """
    diff = list(
        difflib.unified_diff(
            original.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path}",
            tofile=f"b/{path}",
            n=3,
        )
    )

    diff_text = "".join(diff)
    highlighted_diff = highlight_diff(diff_text)

    return highlighted_diff


async def execute_code(code, timeout=10):
    """
    「code_execution_env」仮想環境でPythonコードを実行し、出力を返します。

    Args:
        code (str): 「code_execution_env」仮想環境で実行するPythonコード。必要なインポートをすべて含め、コードが完全で自己完結していることを確認してください。
        timeout (int, optional): 実行のタイムアウト（秒単位）。デフォルトは10です。

    Returns:
        tuple: プロセスIDと実行結果
    """
    global running_processes
    venv_path, activate_script = setup_virtual_environment()

    # このプロセスの一意の識別子を生成する
    process_id = f"process_{len(running_processes)}"

    # コードを一時ファイルに書き込む
    with open(f"{process_id}.py", "w") as f:
        f.write(code)

    # コードを実行するコマンドを準備する
    if sys.platform == "win32":
        command = f'"{activate_script}" && python3 {process_id}.py'
    else:
        command = f'source "{activate_script}" && python3 {process_id}.py'

    # コマンドを実行するプロセスを作成する
    process = await asyncio.create_subprocess_shell(
        command,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        shell=True,
        preexec_fn=None if sys.platform == "win32" else os.setsid,
    )

    # グローバル辞書にプロセスを格納する
    running_processes[process_id] = process

    try:
        # 最初の出力またはタイムアウトを待つ
        stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
        stdout = stdout.decode()
        stderr = stderr.decode()
        return_code = process.returncode
    except asyncio.TimeoutError:
        # タイムアウトした場合、プロセスはまだ実行中です
        stdout = "プロセスが開始され、バックグラウンドで実行中です。"
        stderr = ""
        return_code = "実行中"

    execution_result = f"プロセスID: {process_id}\n\n標準出力:\n{stdout}\n\n標準エラー出力:\n{stderr}\n\nリターンコード: {return_code}"
    return process_id, execution_result


def read_file(path):
    """
    指定されたパスにあるファイルの内容を読み取ります。

    Args:
        path (str): 読み取るファイルの絶対パスまたは相対パス。Windowsシステムでもパス区切りにはスラッシュ（/）を使用します。

    Returns:
        str: ファイルの内容が文字列として返されます。ファイルが存在しないか、読み取れない場合は、適切なエラーメッセージが返されます。
    """
    global file_contents
    try:
        with open(path, "r") as f:
            content = f.read()
        file_contents[path] = content
        return f"ファイル '{path}' が読み取られ、システムプロンプトに保存されました。"
    except Exception as e:
        return f"ファイルの読み取り中にエラーが発生しました: {str(e)}"


def read_multiple_files(paths):
    """
    指定されたパスにある複数のファイルの内容を読み取ります。

    Args:
        paths (list): 読み取るファイルの絶対パスまたは相対パスのリスト。Windowsシステムでもパス区切りにはスラッシュ（/）を使用します。

    Returns:
        str: 各ファイルの読み取りステータスを含む文字列。正常に読み取られたファイルの内容はシステムプロンプトに保存されます。
             ファイルが存在しないか、読み取れない場合は、そのファイルに対して適切なエラーメッセージが返されます。
    """
    global file_contents
    results = []
    for path in paths:
        try:
            with open(path, "r") as f:
                content = f.read()
            file_contents[path] = content
            results.append(
                f"ファイル '{path}' が読み取られ、システムプロンプトに保存されました。"
            )
        except Exception as e:
            results.append(
                f"ファイル '{path}' の読み取り中にエラーが発生しました: {str(e)}"
            )
    return "\n".join(results)


def list_files(path="."):
    """
    指定されたフォルダ内のすべてのファイルとディレクトリを一覧表示します。

    Args:
        path (str, optional): 一覧表示するフォルダの絶対パスまたは相対パス。Windowsシステムでもパス区切りにはスラッシュ（/）を使用します。
                              指定されていない場合は、現在の作業ディレクトリが使用されます。

    Returns:
        str: すべてのファイルとサブディレクトリのリスト。ディレクトリが存在しないか、読み取れない場合は、適切なエラーメッセージが返されます。
    """
    try:
        files = os.listdir(path)
        return "\n".join(files)
    except Exception as e:
        return f"ファイルの一覧表示中にエラーが発生しました: {str(e)}"


def tavily_search(query):
    """
    最新の情報を取得したり、追加のコンテキストを取得したりするために、Tavily APIを使用してウェブ検索を実行します。

    Args:
        query (str): 検索クエリ。可能な限り具体的で詳細なクエリにして、最も関連性の高い結果を取得してください。

    Returns:
        str: 検索結果のサマリー。関連するスニペットとソースURLが含まれます。検索に失敗した場合は、適切なエラーメッセージが返されます。
    """
    try:
        response = tavily.qna_search(query=query, search_depth="advanced")
        return response
    except Exception as e:
        return f"検索の実行中にエラーが発生しました: {str(e)}"


def stop_process(process_id):
    """
    IDによって実行中のプロセスを停止します。

    Args:
        process_id (str): 停止するプロセスのID。長時間実行されるプロセスについては、execute_codeツールによって返されます。

    Returns:
        str: プロセスが停止された場合は成功メッセージ、プロセスが存在しないか停止できない場合はエラーメッセージ
    """
    global running_processes
    if process_id in running_processes:
        process = running_processes[process_id]
        if sys.platform == "win32":
            process.terminate()
        else:
            os.killpg(os.getpgid(process.pid), signal.SIGTERM)
        del running_processes[process_id]
        return f"プロセス {process_id} が停止されました。"
    else:
        return f"ID {process_id} の実行中のプロセスが見つかりませんでした。"


tools = [
    {
        "name": "create_folder",
        "description": "指定されたパスに新しいフォルダを作成します。このツールは、プロジェクト構造に新しいディレクトリを作成する必要がある場合に使用してください。存在しない場合は、必要な親ディレクトリをすべて作成します。ツールは、フォルダが作成されたか、既に存在する場合は成功メッセージを返し、フォルダの作成に問題がある場合はエラーメッセージを返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "フォルダを作成する絶対パスまたは相対パス。Windowsシステムでもパス区切りにはスラッシュ（/）を使用します。",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "create_file",
        "description": "指定されたパスに、指定された内容で新しいファイルを作成します。このツールは、プロジェクト構造に新しいファイルを作成する必要がある場合に使用してください。存在しない場合は、必要な親ディレクトリをすべて作成します。ツールは、ファイルが作成された場合は成功メッセージを返し、ファイルの作成に問題があるか、ファイルが既に存在する場合はエラーメッセージを返します。コンテンツはできるだけ完全で役立つものにする必要があり、必要なインポート、関数定義、コメントを含める必要があります。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "ファイルを作成する絶対パスまたは相対パス。Windowsシステムでもパス区切りにはスラッシュ（/）を使用します。",
                },
                "content": {
                    "type": "string",
                    "description": "ファイルの内容。これには、必要なすべてのコード、コメント、フォーマットを含める必要があります。",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "edit_and_apply",
        "description": "特定の指示と詳細なプロジェクトコンテキストに基づいて、ファイルにAIを活用した改善を適用します。この関数は、ファイルを読み取り、会話履歴と包括的なコード関連プロジェクトコンテキストを使用して、AIでバッチ処理を行います。diffを生成し、ユーザーが変更を適用する前に確認できるようにします。目標は、一貫性を維持し、ファイル間の接続が壊れないようにすることです。このツールは、より広範なプロジェクトコンテキストを理解する必要がある複雑なコード変更に使用してください。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "編集するファイルの絶対パスまたは相対パス。Windowsシステムでもパス区切りにはスラッシュ（/）を使用します。",
                },
                "instructions": {
                    "type": "string",
                    "description": "コードレビューの完了後、<PLANNING>タグの間に変更の計画を立てます。関連する可能性のある追加のソースファイルまたはドキュメントを要求します。計画は重複を避ける必要があり（DRY原則）、保守性と柔軟性のバランスを取る必要があります。このステップでは、トレードオフと実装の選択肢を提示します。利用可能なフレームワークとライブラリを検討し、関連する場合にはそれらの使用を提案します。計画に同意していない場合は、このステップで停止します。同意したら、<OUTPUT>タグの間にコードを生成します。変数名、識別子、文字列リテラルに注意し、特に指示がない限り、元のソースファイルから正確に再現されていることを確認します。慣例に従って命名する場合は、二重コロンで囲み、::UPPERCASE::で囲みます。既存のコードスタイルを維持し、言語に適したイディオムを使用します。最初のバックティックの後に指定された言語でコードブロックを生成します。",
                },
                "project_context": {
                    "type": "string",
                    "description": "最近の変更、新しい変数や関数、ファイル間の相互接続、コーディング標準、編集に影響を与える可能性のあるその他の関連情報など、プロジェクトに関する包括的なコンテキスト。",
                },
            },
            "required": ["path", "instructions", "project_context"],
        },
    },
    {
        "name": "execute_code",
        "description": "「code_execution_env」仮想環境でPythonコードを実行し、出力を返します。このツールは、コードを実行してその出力を見たり、エラーを確認したりする必要がある場合に使用してください。すべてのコード実行はこの分離された環境でのみ行われます。ツールは、実行されたコードの標準出力、標準エラー出力、およびリターンコードを返します。長時間実行されるプロセスは、後で管理するためのプロセスIDを返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "「code_execution_env」仮想環境で実行するPythonコード。必要なインポートをすべて含め、コードが完全で自己完結していることを確認してください。",
                }
            },
            "required": ["code"],
        },
    },
    {
        "name": "stop_process",
        "description": "IDによって実行中のプロセスを停止します。このツールは、execute_codeツールによって開始された長時間実行されるプロセスを終了するために使用する必要があります。プロセスを正常に停止しようとしますが、必要に応じて強制終了する場合があります。ツールは、プロセスが停止された場合は成功メッセージを返し、プロセスが存在しないか停止できない場合はエラーメッセージを返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "process_id": {
                    "type": "string",
                    "description": "停止するプロセスのID。長時間実行されるプロセスについては、execute_codeツールによって返されます。",
                }
            },
            "required": ["process_id"],
        },
    },
    {
        "name": "read_file",
        "description": "指定されたパスにあるファイルの内容を読み取ります。このツールは、既存のファイルの内容を調べる必要がある場合に使用してください。ファイルの内容全体を文字列として返します。ファイルが存在しないか、読み取れない場合は、適切なエラーメッセージが返されます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "読み取るファイルの絶対パスまたは相対パス。Windowsシステムでもパス区切りにはスラッシュ（/）を使用します。",
                }
            },
            "required": ["path"],
        },
    },
    {
        "name": "read_multiple_files",
        "description": "指定されたパスにある複数のファイルの内容を読み取ります。このツールは、複数の既存のファイルの内容を一度に調べる必要がある場合に使用してください。各ファイルの読み取りステータスを返し、正常に読み取られたファイルの内容をシステムプロンプトに保存します。ファイルが存在しないか、読み取れない場合は、そのファイルに対して適切なエラーメッセージが返されます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "paths": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "読み取るファイルの絶対パスまたは相対パスの配列。Windowsシステムでもパス区切りにはスラッシュ（/）を使用します。",
                }
            },
            "required": ["paths"],
        },
    },
    {
        "name": "list_files",
        "description": "指定されたフォルダ内のすべてのファイルとディレクトリを一覧表示します。このツールは、ディレクトリの内容を確認する必要がある場合に使用してください。指定されたパス内のすべてのファイルとサブディレクトリのリストを返します。ディレクトリが存在しないか、読み取れない場合は、適切なエラーメッセージが返されます。",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "一覧表示するフォルダの絶対パスまたは相対パス。Windowsシステムでもパス区切りにはスラッシュ（/）を使用します。指定されていない場合は、現在の作業ディレクトリが使用されます。",
                }
            },
        },
    },
    {
        "name": "tavily_search",
        "description": "最新の情報を取得したり、追加のコンテキストを取得したりするために、Tavily APIを使用してウェブ検索を実行します。このツールは、最新の情報が必要な場合、または検索がユーザーのクエリに対してより良い回答を提供できると感じる場合に使用してください。関連するスニペットとソースURLを含む、検索結果のサマリーを返します。",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "検索クエリ。可能な限り具体的で詳細なクエリにして、最も関連性の高い結果を取得してください。",
                }
            },
            "required": ["query"],
        },
    },
]

from typing import Dict, Any


async def execute_tool(tool_name: str, tool_input: Dict[str, Any]) -> Dict[str, Any]:
    """
    指定されたツールを実行します。

    Args:
        tool_name (str): 実行するツールの名前。
        tool_input (Dict[str, Any]): ツールへの入力。

    Returns:
        Dict[str, Any]: ツールの結果とエラーが発生したかどうかを示すフラグ。
    """
    try:
        result = None
        is_error = False

        if tool_name == "create_folder":
            result = create_folder(tool_input["path"])
        elif tool_name == "create_file":
            result = create_file(tool_input["path"], tool_input.get("content", ""))
        elif tool_name == "edit_and_apply":
            result = await edit_and_apply(
                tool_input["path"],
                tool_input["instructions"],
                tool_input["project_context"],
                is_automode=automode,
            )
        elif tool_name == "read_file":
            result = read_file(tool_input["path"])
        elif tool_name == "read_multiple_files":
            result = read_multiple_files(tool_input["paths"])
        elif tool_name == "list_files":
            result = list_files(tool_input.get("path", "."))
        elif tool_name == "tavily_search":
            result = tavily_search(tool_input["query"])
        elif tool_name == "stop_process":
            result = stop_process(tool_input["process_id"])
        elif tool_name == "execute_code":
            process_id, execution_result = await execute_code(tool_input["code"])
            analysis_task = asyncio.create_task(
                send_to_ai_for_executing(tool_input["code"], execution_result)
            )
            analysis = await analysis_task
            result = f"{execution_result}\n\n分析:\n{analysis}"
            if process_id in running_processes:
                result += "\n\n注意: プロセスはまだバックグラウンドで実行中です。"
        else:
            is_error = True
            result = f"不明なツール: {tool_name}"

        return {"content": result, "is_error": is_error}
    except KeyError as e:
        logging.error(f"ツール {tool_name} に必要なパラメータ {str(e)} がありません")
        return {
            "content": f"エラー: ツール {tool_name} に必要なパラメータ {str(e)} がありません",
            "is_error": True,
        }
    except Exception as e:
        logging.error(f"ツール {tool_name} の実行中にエラーが発生しました: {str(e)}")
        return {
            "content": f"ツール {tool_name} の実行中にエラーが発生しました: {str(e)}",
            "is_error": True,
        }


def encode_image_to_base64(image_path):
    """
    画像をbase64にエンコードします。

    Args:
        image_path (str): エンコードする画像のパス。

    Returns:
        str: 画像のbase64エンコーディング。エラーが発生した場合は、エラーメッセージを返します。
    """
    try:
        with Image.open(image_path) as img:
            max_size = (1024, 1024)
            img.thumbnail(max_size, Image.DEFAULT_STRATEGY)
            if img.mode != "RGB":
                img = img.convert("RGB")
            img_byte_arr = io.BytesIO()
            img.save(img_byte_arr, format="JPEG")
            return base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")
    except Exception as e:
        return f"画像のエンコード中にエラーが発生しました: {str(e)}"


async def send_to_ai_for_executing(code, execution_result):
    """
    コードと実行結果を分析のためにAIに送信します。

    Args:
        code (str): 実行されたコード。
        execution_result (str): コードの実行結果。

    Returns:
        str: AIによる分析結果。
    """
    global code_execution_tokens

    try:
        system_prompt = f"""
        あなたはAIコード実行エージェントです。あなたの仕事は、「code_execution_env」仮想環境からの提供されたコードとその実行結果を分析し、何がうまくいき、何がうまくいかなかったか、および重要な観察結果の簡潔な要約を提供することです。次の手順に従ってください。

        1. 「code_execution_env」仮想環境で実行されたコードを確認します。
        {code}

        2. 「code_execution_env」仮想環境からの実行結果を分析します。
        {execution_result}

        3. 以下の簡単な要約を提供します。
           - 仮想環境で正常に実行されたコードの部分
           - 仮想環境で発生したエラーまたは予期しない動作
           - 環境の分離された性質を考慮した、問題の潜在的な改善または修正
           - 仮想環境内でのコードのパフォーマンスまたは出力に関する重要な観察結果
           - 実行がタイムアウトした場合、これが何を意味する可能性があるか説明します（例：長時間実行されるプロセス、無限ループ）

        簡潔にして、「code_execution_env」仮想環境内でのコード実行の最も重要な側面に焦点を当ててください。

        重要：分析と観察結果のみを提供してください。役割の説明や序文を含めないでください。
        """

        response = client.messages.create(
            model=CODEEXECUTIONMODEL,
            max_tokens=2000,
            system=system_prompt,
            messages=[
                {
                    "role": "user",
                    "content": f"「code_execution_env」仮想環境からのこのコード実行を分析してください:\n\nコード:\n{code}\n\n実行結果:\n{execution_result}",
                }
            ],
        )

        # コード実行のトークン使用量を更新する
        code_execution_tokens["input"] += response.usage.input_tokens
        code_execution_tokens["output"] += response.usage.output_tokens

        analysis = response.content[0].text

        return analysis

    except Exception as e:
        console.print(
            f"AIコード実行分析中にエラーが発生しました: {str(e)}", style="bold red"
        )
        return f"「code_execution_env」からのコード実行の分析中にエラーが発生しました: {str(e)}"


def save_chat():
    """
    チャットをMarkdownファイルに保存します。

    Returns:
        str: 保存されたチャットファイルの名前。
    """
    # ファイル名を生成する
    now = datetime.datetime.now()
    filename = f"チャット_{now.strftime('%H%M')}.md"

    # 会話履歴をフォーマットする
    formatted_chat = "# Claude-3-Sonnetエンジニアチャットログ\n\n"
    for message in conversation_history:
        if message["role"] == "user":
            formatted_chat += f"## ユーザー\n\n{message['content']}\n\n"
        elif message["role"] == "assistant":
            if isinstance(message["content"], str):
                formatted_chat += f"## Claude\n\n{message['content']}\n\n"
            elif isinstance(message["content"], list):
                for content in message["content"]:
                    if content["type"] == "tool_use":
                        formatted_chat += f"### ツールの使用: {content['name']}\n\n```json\n{json.dumps(content['input'], indent=2)}\n```\n\n"
                    elif content["type"] == "text":
                        formatted_chat += f"## Claude\n\n{content['text']}\n\n"
        elif message["role"] == "user" and isinstance(message["content"], list):
            for content in message["content"]:
                if content["type"] == "tool_result":
                    formatted_chat += (
                        f"### ツールの結果\n\n```\n{content['content']}\n```\n\n"
                    )

    # ファイルに保存する
    with open(filename, "w", encoding="utf-8") as f:
        f.write(formatted_chat)

    return filename


async def chat_with_claude(
    user_input, image_path=None, current_iteration=None, max_iterations=None
):
    """
    Claudeとチャットします。

    Args:
        user_input (str): ユーザーの入力。
        image_path (str, optional): 画像のパス。デフォルトはNone。
        current_iteration (int, optional): 現在の自動モードの反復回数。デフォルトはNone。
        max_iterations (int, optional): 自動モードの最大反復回数。デフォルトはNone。

    Returns:
        tuple: アシスタントの応答と継続を終了するかどうかを示すフラグ。
    """
    global conversation_history, automode, main_model_tokens

    # この関数は、呼び出し間でコンテキストを維持するMAINMODELを使用します
    current_conversation = []

    if image_path:
        console.print(
            Panel(
                f"パス: {image_path} の画像を処理しています",
                title_align="left",
                title="画像処理",
                expand=False,
                style="yellow",
            )
        )
        image_base64 = encode_image_to_base64(image_path)

        if image_base64.startswith("エラー"):
            console.print(
                Panel(
                    f"画像のエンコード中にエラーが発生しました: {image_base64}",
                    title="エラー",
                    style="bold red",
                )
            )
            return "画像の処理中にエラーが発生しました。もう一度試してください。", False

        image_message = {
            "role": "user",
            "content": [
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": image_base64,
                    },
                },
                {"type": "text", "text": f"画像のユーザー入力: {user_input}"},
            ],
        }
        current_conversation.append(image_message)
        console.print(
            Panel(
                "画像メッセージが会話履歴に追加されました",
                title_align="left",
                title="画像が追加されました",
                style="green",
            )
        )
    else:
        current_conversation.append({"role": "user", "content": user_input})

    # コンテキストを維持するために会話履歴をフィルタリングする
    filtered_conversation_history = []
    for message in conversation_history:
        if isinstance(message["content"], list):
            filtered_content = [
                content
                for content in message["content"]
                if content.get("type") != "tool_result"
                or (
                    content.get("type") == "tool_result"
                    and not any(
                        keyword in content.get("output", "")
                        for keyword in [
                            "システムプロンプト内のファイルの内容が更新されました",
                            "ファイルが作成され、システムプロンプトに追加されました",
                            "が読み取られ、システムプロンプトに保存されました",
                        ]
                    )
                )
            ]
            if filtered_content:
                filtered_conversation_history.append(
                    {**message, "content": filtered_content}
                )
        else:
            filtered_conversation_history.append(message)

    # コンテキストを維持するために、フィルタリングされた履歴と現在の会話を組み合わせる
    messages = filtered_conversation_history + current_conversation

    try:
        # MAINMODEL呼び出し、コンテキストを維持します
        response = client.messages.create(
            model=MAINMODEL,
            max_tokens=8000,
            system=update_system_prompt(current_iteration, max_iterations),
            extra_headers={"anthropic-beta": "max-tokens-3-5-sonnet-2024-07-15"},
            messages=messages,
            tools=tools,
            tool_choice={"type": "auto"},
        )
        # MAINMODELのトークン使用量を更新する
        main_model_tokens["input"] += response.usage.input_tokens
        main_model_tokens["output"] += response.usage.output_tokens
    except APIStatusError as e:
        if e.status_code == 429:
            console.print(
                Panel(
                    "レート制限を超えました。少し遅れてから再試行します...",
                    title="APIエラー",
                    style="bold yellow",
                )
            )
            time.sleep(5)
            return await chat_with_claude(
                user_input, image_path, current_iteration, max_iterations
            )
        else:
            console.print(
                Panel(f"APIエラー: {str(e)}", title="APIエラー", style="bold red")
            )
            return "AIとの通信中にエラーが発生しました。もう一度試してください。", False
    except APIError as e:
        console.print(
            Panel(f"APIエラー: {str(e)}", title="APIエラー", style="bold red")
        )
        return "AIとの通信中にエラーが発生しました。もう一度試してください。", False

    assistant_response = ""
    exit_continuation = False
    tool_uses = []

    for content_block in response.content:
        if content_block.type == "text":
            assistant_response += content_block.text
            if CONTINUATION_EXIT_PHRASE in content_block.text:
                exit_continuation = True
        elif content_block.type == "tool_use":
            tool_uses.append(content_block)

    console.print(
        Panel(
            Markdown(assistant_response),
            title="Claudeの応答",
            title_align="left",
            border_style="blue",
            expand=False,
        )
    )

    # コンテキスト内のファイルを表示する
    if file_contents:
        files_in_context = "\n".join(file_contents.keys())
    else:
        files_in_context = "コンテキスト内にファイルがありません。ファイルを読み取るか、作成するか、編集して追加してください。"
    console.print(
        Panel(
            files_in_context,
            title="コンテキスト内のファイル",
            title_align="left",
            border_style="white",
            expand=False,
        )
    )

    for tool_use in tool_uses:
        tool_name = tool_use.name
        tool_input = tool_use.input
        tool_use_id = tool_use.id

        console.print(Panel(f"使用されたツール: {tool_name}", style="green"))
        console.print(
            Panel(f"ツールの入力: {json.dumps(tool_input, indent=2)}", style="green")
        )

        tool_result = await execute_tool(tool_name, tool_input)

        if tool_result["is_error"]:
            console.print(
                Panel(tool_result["content"], title="ツールのエラー", style="bold red")
            )
        else:
            console.print(
                Panel(
                    tool_result["content"],
                    title_align="left",
                    title="ツールの結果",
                    style="green",
                )
            )

        current_conversation.append(
            {
                "role": "assistant",
                "content": [
                    {
                        "type": "tool_use",
                        "id": tool_use_id,
                        "name": tool_name,
                        "input": tool_input,
                    }
                ],
            }
        )

        current_conversation.append(
            {
                "role": "user",
                "content": [
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": tool_result["content"],
                        "is_error": tool_result["is_error"],
                    }
                ],
            }
        )

        # 該当する場合、file_contents辞書を更新する
        if (
            tool_name in ["create_file", "edit_and_apply", "read_file"]
            and not tool_result["is_error"]
        ):
            if "path" in tool_input:
                file_path = tool_input["path"]
                if (
                    "システムプロンプト内のファイルの内容が更新されました"
                    in tool_result["content"]
                    or "ファイルが作成され、システムプロンプトに追加されました"
                    in tool_result["content"]
                    or "が読み取られ、システムプロンプトに保存されました"
                    in tool_result["content"]
                ):
                    # file_contents辞書はツール関数で既に更新されています
                    pass

        messages = filtered_conversation_history + current_conversation

        try:
            tool_response = client.messages.create(
                model=TOOLCHECKERMODEL,
                max_tokens=8000,
                system=update_system_prompt(current_iteration, max_iterations),
                extra_headers={"anthropic-beta": "max-tokens-3-5-sonnet-2024-07-15"},
                messages=messages,
                tools=tools,
                tool_choice={"type": "auto"},
            )
            # ツールチェッカーのトークン使用量を更新する
            tool_checker_tokens["input"] += tool_response.usage.input_tokens
            tool_checker_tokens["output"] += tool_response.usage.output_tokens

            tool_checker_response = ""
            for tool_content_block in tool_response.content:
                if tool_content_block.type == "text":
                    tool_checker_response += tool_content_block.text
            console.print(
                Panel(
                    Markdown(tool_checker_response),
                    title="ツールの結果に対するClaudeの応答",
                    title_align="left",
                    border_style="blue",
                    expand=False,
                )
            )
            assistant_response += "\n\n" + tool_checker_response
        except APIError as e:
            error_message = f"ツール応答中にエラーが発生しました: {str(e)}"
            console.print(Panel(error_message, title="エラー", style="bold red"))
            assistant_response += f"\n\n{error_message}"

    if assistant_response:
        current_conversation.append(
            {"role": "assistant", "content": assistant_response}
        )

    conversation_history = messages + [
        {"role": "assistant", "content": assistant_response}
    ]

    # 最後にトークン使用量を表示する
    display_token_usage()

    return assistant_response, exit_continuation


def reset_code_editor_memory():
    """
    コードエディタのメモリをリセットします。
    """
    global code_editor_memory
    code_editor_memory = []
    console.print(
        Panel(
            "コードエディタのメモリがリセットされました。",
            title="リセット",
            style="bold green",
        )
    )


def reset_conversation():
    """
    会話履歴、トークン数、ファイルの内容、コードエディタのメモリ、コードエディタのファイルをリセットします。
    """
    global conversation_history, main_model_tokens, tool_checker_tokens, code_editor_tokens, code_execution_tokens, file_contents, code_editor_files
    conversation_history = []
    main_model_tokens = {"input": 0, "output": 0}
    tool_checker_tokens = {"input": 0, "output": 0}
    code_editor_tokens = {"input": 0, "output": 0}
    code_execution_tokens = {"input": 0, "output": 0}
    file_contents = {}
    code_editor_files = set()
    reset_code_editor_memory()
    console.print(
        Panel(
            "会話履歴、トークン数、ファイルの内容、コードエディタのメモリ、コードエディタのファイルがリセットされました。",
            title="リセット",
            style="bold green",
        )
    )
    display_token_usage()


def display_token_usage():
    """
    トークンの使用量を表示します。
    """
    from rich.table import Table
    from rich.panel import Panel
    from rich.box import ROUNDED

    table = Table(box=ROUNDED)
    table.add_column("モデル", style="cyan")
    table.add_column("入力", style="magenta")
    table.add_column("出力", style="magenta")
    table.add_column("合計", style="green")
    table.add_column(f"コンテキストの割合 ({MAX_CONTEXT_TOKENS:,})", style="yellow")
    table.add_column("コスト ($)", style="red")

    model_costs = {
        "メインモデル": {"input": 3.00, "output": 15.00, "has_context": True},
        "ツールチェッカー": {"input": 3.00, "output": 15.00, "has_context": False},
        "コードエディタ": {"input": 3.00, "output": 15.00, "has_context": True},
        "コード実行": {"input": 3.00, "output": 15.00, "has_context": False},
    }

    total_input = 0
    total_output = 0
    total_cost = 0
    total_context_tokens = 0

    for model, tokens in [
        ("メインモデル", main_model_tokens),
        ("ツールチェッカー", tool_checker_tokens),
        ("コードエディタ", code_editor_tokens),
        ("コード実行", code_execution_tokens),
    ]:
        input_tokens = tokens["input"]
        output_tokens = tokens["output"]
        total_tokens = input_tokens + output_tokens

        total_input += input_tokens
        total_output += output_tokens

        input_cost = (input_tokens / 1_000_000) * model_costs[model]["input"]
        output_cost = (output_tokens / 1_000_000) * model_costs[model]["output"]
        model_cost = input_cost + output_cost
        total_cost += model_cost

        if model_costs[model]["has_context"]:
            total_context_tokens += total_tokens
            percentage = (total_tokens / MAX_CONTEXT_TOKENS) * 100
        else:
            percentage = 0

        table.add_row(
            model,
            f"{input_tokens:,}",
            f"{output_tokens:,}",
            f"{total_tokens:,}",
            (
                f"{percentage:.2f}%"
                if model_costs[model]["has_context"]
                else "コンテキストを保存しません"
            ),
            f"${model_cost:.3f}",
        )

    grand_total = total_input + total_output
    total_percentage = (total_context_tokens / MAX_CONTEXT_TOKENS) * 100

    table.add_row(
        "合計",
        f"{total_input:,}",
        f"{total_output:,}",
        f"{grand_total:,}",
        "",  # 「コンテキストの割合」列は空の文字列
        f"${total_cost:.3f}",
        style="bold",
    )

    console.print(table)


async def main():
    """
    メインのチャットループ。
    """
    global automode, conversation_history
    console.print(
        Panel(
            "マルチエージェントと画像サポートを備えたClaude-3-Sonnetエンジニアチャットへようこそ！",
            title="ようこそ",
            style="bold green",
        )
    )
    console.print("会話を終了するには「exit」と入力してください。")
    console.print("メッセージに画像を含めるには「image」と入力してください。")
    console.print(
        "特定の反復回数で自律モードに入るには「automode [回数]」と入力してください。"
    )
    console.print("会話履歴をクリアするには「reset」と入力してください。")
    console.print(
        "会話をMarkdownファイルに保存するには「save chat」と入力してください。"
    )
    console.print(
        "自動モード中は、Ctrl+Cを押して自動モードを終了し、通常のチャットに戻ることができます。"
    )

    while True:
        user_input = await get_user_input()

        if user_input.lower() == "exit":
            console.print(
                Panel(
                    "チャットにご参加いただきありがとうございます。さようなら！",
                    title_align="left",
                    title="さようなら",
                    style="bold green",
                )
            )
            break

        if user_input.lower() == "reset":
            reset_conversation()
            continue

        if user_input.lower() == "save chat":
            filename = save_chat()
            console.print(
                Panel(
                    f"チャットは{filename}に保存されました",
                    title="チャットが保存されました",
                    style="bold green",
                )
            )
            continue

        if user_input.lower() == "image":
            image_path = (
                (
                    await get_user_input(
                        "画像をここにドラッグアンドドロップして、Enterキーを押してください: "
                    )
                )
                .strip()
                .replace("'", "")
            )

            if os.path.isfile(image_path):
                user_input = await get_user_input("あなた (画像のプロンプト): ")
                response, _ = await chat_with_claude(user_input, image_path)
            else:
                console.print(
                    Panel(
                        "無効な画像パスです。もう一度試してください。",
                        title="エラー",
                        style="bold red",
                    )
                )
                continue
        elif user_input.lower().startswith("automode"):
            try:
                parts = user_input.split()
                if len(parts) > 1 and parts[1].isdigit():
                    max_iterations = int(parts[1])
                else:
                    max_iterations = MAX_CONTINUATION_ITERATIONS

                automode = True
                console.print(
                    Panel(
                        f"{max_iterations}回の反復で自動モードに入ります。自動モードの目標を入力してください。",
                        title_align="left",
                        title="自動モード",
                        style="bold yellow",
                    )
                )
                console.print(
                    Panel(
                        "自動モードループを終了するには、Ctrl+Cを押してください。",
                        style="bold yellow",
                    )
                )
                user_input = await get_user_input()

                iteration_count = 0
                try:
                    while automode and iteration_count < max_iterations:
                        response, exit_continuation = await chat_with_claude(
                            user_input,
                            current_iteration=iteration_count + 1,
                            max_iterations=max_iterations,
                        )

                        if exit_continuation or CONTINUATION_EXIT_PHRASE in response:
                            console.print(
                                Panel(
                                    "自動モードが完了しました。",
                                    title_align="left",
                                    title="自動モード",
                                    style="green",
                                )
                            )
                            automode = False
                        else:
                            console.print(
                                Panel(
                                    f"継続反復{iteration_count + 1}が完了しました。自動モードを終了するには、Ctrl+Cを押してください。 ",
                                    title_align="left",
                                    title="自動モード",
                                    style="yellow",
                                )
                            )
                            user_input = "次のステップに進みます。または、最初のリクエストで確立された結果が達成されたと思われる場合は、「AUTOMODE_COMPLETE」と言って停止してください。"
                        iteration_count += 1

                        if iteration_count >= max_iterations:
                            console.print(
                                Panel(
                                    "最大反復回数に達しました。自動モードを終了します。",
                                    title_align="left",
                                    title="自動モード",
                                    style="bold red",
                                )
                            )
                            automode = False
                except KeyboardInterrupt:
                    console.print(
                        Panel(
                            "\nユーザーによって自動モードが中断されました。自動モードを終了します。",
                            title_align="left",
                            title="自動モード",
                            style="bold red",
                        )
                    )
                    automode = False
                    if (
                        conversation_history
                        and conversation_history[-1]["role"] == "user"
                    ):
                        conversation_history.append(
                            {
                                "role": "assistant",
                                "content": "自動モードが中断されました。他に何かお手伝いできることはありますか？",
                            }
                        )
            except KeyboardInterrupt:
                console.print(
                    Panel(
                        "\nユーザーによって自動モードが中断されました。自動モードを終了します。",
                        title_align="left",
                        title="自動モード",
                        style="bold red",
                    )
                )
                automode = False
                if conversation_history and conversation_history[-1]["role"] == "user":
                    conversation_history.append(
                        {
                            "role": "assistant",
                            "content": "自動モードが中断されました。他に何かお手伝いできることはありますか？",
                        }
                    )

            console.print(
                Panel(
                    "自動モードを終了しました。通常のチャットに戻ります。",
                    style="green",
                )
            )
        else:
            response, _ = await chat_with_claude(user_input)


if __name__ == "__main__":
    asyncio.run(main())
