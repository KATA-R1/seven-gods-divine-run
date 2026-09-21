# YouTube 検索 & ダウンローダー

YouTube Data API v3 で動画を検索し、ブラウザ上で選択した動画だけを
`yt-dlp` でダウンロードするローカル Streamlit アプリです。映像・音声は
再エンコードせず、ffmpeg による結合（mux）のみを行います。

初回セットアップ、APIキー取得、OAuth設定、検索・ダウンロード・AI生成・YouTubeアップロードまでの
詳しい手順は [GUIDE.md](GUIDE.md) を参照してください。

## 前提

- Windows 10 / 11
- macOS
- Windows: Python / ffmpeg / Deno は初回起動時に自動準備
- macOS: Python 3 が必要。Pythonパッケージとffmpegは初回起動時に自動準備
- インターネット接続
- YouTube Data API v3 の API キー

## このPCですぐ起動する

Windowsでは、`start_app.bat` をダブルクリックすると起動できます。
端末から起動する場合は次を実行します。

```powershell
.\start_app.bat
```

macOSでは、`start_app_macos.command` をダブルクリックします。
初回起動時に必要なPythonパッケージとffmpegを `.runtime` に準備します。
もし「開発元を確認できない」等の警告が出る場合は、Finderで右クリックして「開く」を選んでください。

アプリのURLは通常 `http://localhost:8501` です。

画面上部には次のページ切り替えボタンがあります。

- アカウント設定
- YouTube検索＆ダウンロード
- YouTubeアップロード

ページ切り替えは `?page=settings` のようにURLへ反映されるため、ブラウザの戻る/進む操作も使えます。

## ほかのPCへ配布する

配布用ZIPは `dist` フォルダに作成されます。

```text
dist\YouTube-Search-Downloader.zip
dist\YouTube-Search-Downloader-mac.zip
```

Windowsの配布先では次の操作だけで利用できます。

1. ZIPを任意のフォルダへ展開します。
2. `start_app.bat` をダブルクリックします。
3. 初回のみ必要なツールが自動でダウンロードされます。
4. セットアップ完了後、デスクトップに
   **YouTube Search Downloader** ショートカットが作成されます。

macOSの配布先では次の操作で利用できます。

1. `YouTube-Search-Downloader-mac.zip` を任意のフォルダへ展開します。
2. `start_app_macos.command` をダブルクリックします。
3. 警告が出る場合は、右クリックして「開く」を選びます。
4. 初回のみ必要なPythonパッケージとffmpegが自動で準備されます。

Windows版の自動セットアップは、プロジェクト内の `.runtime` フォルダへ以下を配置します。

- ポータブル Python 3.12
- Pythonパッケージ（Streamlit、yt-dlp、YouTube APIクライアント等）
- ポータブル ffmpeg / ffprobe
- ポータブル Deno

管理者権限やシステムのPATH変更は不要です。初回のみインターネット接続と
約1GBの空き容量が必要です。対応環境は64bit版 Windows 10 / 11です。
APIキーやダウンロード動画、現在のPCの `.runtime` は配布用ZIPに含まれません。

macOS版は、Macに入っている `python3` を使って `.runtime/venv` を作成します。
`python3` がない場合は、先にPython 3をインストールしてください。

## API キーの取得

1. [Google Cloud Console](https://console.cloud.google.com/) でプロジェクトを
   作成します。
2. 「API とサービス」から **YouTube Data API v3** を有効にします。
3. 「認証情報」→「認証情報を作成」→「API キー」でキーを作成します。

読み取り専用の検索には、サービスアカウント、OAuth 同意画面、JSON キーは
不要です。安全のため、Google Cloud Console で API の制限を
「YouTube Data API v3」に設定することを推奨します。

## 手動でのセットアップと起動

PowerShell でこのフォルダを開き、次を実行します。

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
streamlit run app.py --server.address=127.0.0.1
```

ブラウザが自動で開かない場合は、端末に表示されたローカル URL を開きます。
通常は自動セットアップ付きの `start_app.bat` を使えば、この手順は不要です。

## API キー・OAuthの設定

通常は、アプリ上部の「初期設定（APIキー / OpenAIキー / OAuth）」から設定してください。
フォルダを開いてファイルを直接編集しなくても、次をUI上で保存できます。

- YouTube Data API v3キー
- OpenAI APIキー
- YouTubeアップロード用OAuthクライアントJSON
- 複数アカウント・複数チャンネル用の設定プロファイル

複数のGoogleアカウントやブランドチャンネルを使う場合は、プロファイルを分けてください。
プロファイルごとにOAuth JSONとOAuthトークンが分かれるため、投稿先チャンネルの混同を防ぎやすくなります。

設定は主に次へ保存されます。

```text
.streamlit/settings_profiles.json
.streamlit/profiles/
```

従来方式として、`.streamlit/secrets.toml` や環境変数からも読み込めます。
手動で `secrets.toml` を使う場合:

```powershell
New-Item -ItemType Directory -Force .streamlit
notepad .streamlit\secrets.toml
```

ファイルの内容:

```toml
YOUTUBE_API_KEY = "ここにAPIキー"
```

環境変数を現在の PowerShell セッションだけに設定する場合:

```powershell
$env:YOUTUBE_API_KEY = "ここにAPIキー"
streamlit run app.py
```

`secrets.toml` は `.gitignore` に登録済みです。API キーをソースコードへ
書き込まないでください。

OpenAI API を使って要約・タイトル案を作る場合は、同じ `secrets.toml` に
次のように追加できます。

```toml
OPENAI_API_KEY = "ここにOpenAI APIキー"
```

OpenAI API キーは要約・タイトル案を作る場合だけ必要です。字幕取得と
`transcript.txt` 作成だけなら OpenAI API は使いません。
要約・タイトル案生成の既定モデルは `gpt-5.5` です。アカウントで利用できない場合や
コストを抑えたい場合は、画面の「OpenAIモデル」欄で別のモデル名に変更できます。

## 使い方

1. キーワード、取得モード、開始年と終了年を指定して「検索」を押します。
2. 表の「選択」列で動画を選びます。「全選択」「全解除」も利用できます。
3. 「ダウンロード後処理（字幕・要約・タイトル案・サムネイル）」を確認します。
   - 「YouTube字幕・自動字幕を取得して transcript.txt を作成する」を有効にすると、
     日本語字幕または日本語自動字幕を取得します。
   - 「取得した文字起こしから要約・タイトル案を作成する」は既定でONです。
     OpenAI API を使って `summary.md` を作成します。
   - 「要約をもとにサムネイル画像PNGを生成する」も既定でONです。
     OpenAI API を使って `thumbnail.png` を作成します。
   - OpenAI APIキーが未設定の場合は、動画保存と字幕取得だけ行います。
     後からアップロード画面で要約・タイトル案やサムネイルを生成できます。
4. 出力先（既定値 `./downloads`）を確認し、
   「選択した動画をダウンロード」を押します。

検索結果では、ショート動画を避けるために再生時間が3分未満の動画を除外します。
一覧には「再生時間」列も表示されます。
また、指定した出力先フォルダに保存済みの動画は検索結果から非表示になります。
保存済み判定には、出力先フォルダ内の `.downloaded_video_ids.json`、動画ごとの
`upload_metadata.json`、ファイル名やフォルダ名に含まれる `[videoId]` を使います。

新規ダウンロード分は、動画ごとにフォルダ化されます。

```text
downloads/
  動画タイトル [videoId]/
    video.mkv
    subtitle.ja.manual.vtt
    transcript.txt
    summary.md
    thumbnail.png
    thumbnail_prompt.txt
    upload_metadata.json
```

`manual` は投稿者が付けた字幕、`auto` は YouTube の自動字幕です。
指定した言語の字幕がない動画では、動画だけ保存され、字幕処理はスキップされます。
要約時には、自動字幕に含まれる誤字、誤変換、不自然な文章や単語を、意味を変えない範囲で
校正してから要約します。タイトル案とサムネイル案は、内容に含まれる具体的な数値、金額、
期間、割合などを優先的に活かし、少し尖った興味を引く表現にします。サムネイル生成では、
内容に合う場合に図、チャート、矢印、比較、Before/After などの視覚要素も使います。

## YouTubeアップロード

上部の「YouTubeアップロード」ページから、生成済み素材をYouTubeへ投稿できます。
安全のため、公開設定の既定値は「非公開」です。

アップロードには API キーではなく OAuth クライアントJSONが必要です。
通常は「アカウント設定」ページでOAuth JSONを保存し、アップロードページの
「アップロードに使うアカウント / 設定プロファイル」で使うプロファイルを選びます。
初回アップロード時にGoogleログイン画面が開き、認証後のトークンはプロファイルごとに保存されます。

アップロード画面では以下を確認・編集できます。

- 投稿する動画セット
- 要約・タイトル案を後から生成
- サムネイルプレビュー
- サムネイルだけ再生成
- `summary.md` から読み取ったタイトル候補
- 投稿タイトル
- 説明欄: 固定文章 + 生成要約文 + ハッシュタグ
- 固定文章テンプレート
- 動画タグ
- 公開設定（非公開 / 限定公開 / 公開 / 予約公開）

コメント欄ON/OFF、収益化、終了画面、カードなど、このツールで設定できない詳細項目は
投稿後にYouTube Studioで確認してください。

サムネイルが2MBを超える場合は、YouTubeアップロード用に `thumbnail_upload.jpg` へ自動圧縮します。
アップロード成功後、`upload_metadata.json` に投稿先URL、選択タイトル、説明欄、タグなどを保存します。

他人の動画や素材を再投稿する場合は、著作権・利用許可・YouTubeポリシーを必ず確認してください。
自分の動画、許可済み素材、再利用可能な素材だけを対象にしてください。

検索は指定した各年につき API の `search.list` を1回呼び、1回あたり
100ユニットを消費します。既定値は直近3年です。同じ条件を同じセッションで
再検索した場合は保存済み結果を再利用し、API を再度呼びません。

ダウンロード設定は `bv*+ba/b`、結合先は MKV です。MP4 変換、解像度変更、
画質変更などの再エンコードは行いません。1本が失敗しても残りの処理は
継続し、動画ごとの結果を画面に表示します。
