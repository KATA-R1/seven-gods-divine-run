# YouTube検索・ダウンロード・AI要約・サムネイル生成・アップロード 使い方ガイド

このガイドは、このアプリを初めて使う人が迷わないように、必要なアカウント、APIキー、OAuth設定、普段の操作、アップロードまでをまとめたものです。

このアプリでできることは次の通りです。

```text
YouTube検索
↓
動画選択
↓
動画ダウンロード
↓
字幕・自動字幕取得
↓
文字起こし整形
↓
AI要約・タイトル案生成
↓
AIサムネイル画像生成
↓
YouTubeへアップロード
```

重要: 他人の動画や素材を再投稿する場合は、著作権・利用許可・YouTubeポリシーを必ず確認してください。自分の動画、許可済み素材、再利用可能な素材だけを対象にしてください。

---

## 1. 必要なアカウントとキー

このアプリでは、用途ごとに3種類の認証情報を使います。

| 用途 | 必要なもの | 使う場面 |
|---|---|---|
| YouTube検索 | YouTube Data APIキー | キーワード検索、再生回数、チャンネル情報取得 |
| AI要約・タイトル案・サムネイル生成・英語字幕翻訳 | OpenAI APIキー | `summary.md`、`thumbnail.png`、日本語字幕の生成 |
| YouTubeアップロード | Google OAuthクライアントJSON | 動画投稿、サムネイル設定 |

おすすめは、Google Cloudのプロジェクトと、実際に投稿するYouTubeチャンネルのGoogleアカウントを同じにすることです。  
別アカウントでも可能ですが、初回OAuth認証時に「投稿したいYouTubeチャンネルを管理できるGoogleアカウント」でログインする必要があります。

---

## 2. 起動方法

このフォルダにある `start_app.bat` をダブルクリックします。

初回起動時は、必要なツールが自動でダウンロードされます。

通常、ブラウザで次のURLが開きます。

```text
http://127.0.0.1:8501
```

ブラウザが自動で開かない場合は、手動で上のURLを開いてください。

---

## 3. 画面構成

アプリ上部に、次の3つのページ切り替えボタンがあります。

```text
アカウント設定
YouTube検索＆ダウンロード
YouTubeアップロード
```

それぞれの役割は次の通りです。

| ページ | できること |
|---|---|
| アカウント設定 | APIキー、OpenAIキー、OAuth JSON、複数プロファイルの管理 |
| YouTube検索＆ダウンロード | 動画検索、選択、ダウンロード、字幕取得、要約、サムネイル生成 |
| YouTubeアップロード | ダウンロード済み動画の投稿、タイトル・説明欄・サムネイル設定 |

まずは「アカウント設定」で必要なキーとOAuth JSONを保存し、その後「YouTube検索＆ダウンロード」「YouTubeアップロード」を使います。

ページ切り替えはURLにも反映されます。

```text
?page=settings
?page=search
?page=upload
```

そのため、ブラウザの「戻る」「進む」で前後のページに戻れるようになっています。

---

## 4. 初期設定画面と認証情報の保存場所

アプリ上部の「初期設定（APIキー / OpenAIキー / OAuth）」から、必要なキーやOAuth JSONを保存できます。
通常はフォルダを開いてテキスト編集する必要はありません。

初期設定画面でできること:

```text
YouTube Data API v3キーの保存
OpenAI APIキーの保存
OAuthクライアントJSONのアップロード保存
設定プロファイルの追加・切り替え・削除
OAuth認証トークンの削除・再認証
```

複数のGoogleアカウントや複数のYouTubeチャンネルを使う場合は、設定プロファイルを分けてください。
プロファイルを分けると、OAuth JSONやOAuth認証トークンが混ざりにくくなります。

例:

```text
既定
ブランドch
検証用
```

プロファイル設定は次に保存されます。

```text
.streamlit/settings_profiles.json
.streamlit/profiles/
```

古い方式として、APIキーは次のファイルからも読み込めます。

```text
.streamlit/secrets.toml
```

例:

```toml
YOUTUBE_API_KEY = "ここにYouTube Data APIキー"
OPENAI_API_KEY = "ここにOpenAI APIキー"
```

YouTubeアップロード用のOAuthクライアントJSONは次の場所に置きます。

```text
.streamlit/client_secret.json
```

ただし、複数プロファイルを使う場合は、プロファイルごとに次のような場所へ自動保存されます。

```text
.streamlit/profiles/プロファイル名_xxxxxxxx/client_secret.json
.streamlit/profiles/プロファイル名_xxxxxxxx/youtube_upload_token.json
```

初回アップロード後、認証トークンは自動で次に保存されます。

```text
.streamlit/youtube_upload_token.json
```

これらのファイルは秘密情報です。他人に渡すZIPや共有フォルダには含めないでください。

---

## 5. YouTube Data APIキーの取得方法

YouTube検索に必要です。アップロードには使いません。

1. Google Cloud Consoleを開きます。

   https://console.cloud.google.com/

2. プロジェクトを作成します。

   例:

   ```text
   youtube-search-upload-tool
   ```

3. 作成したプロジェクトを選択します。

4. YouTube Data API v3を有効化します。

   直接開く場合:

   https://console.cloud.google.com/apis/library/youtube.googleapis.com

5. 「認証情報」ページを開きます。

   https://console.cloud.google.com/apis/credentials

6. 「認証情報を作成」→「APIキー」を選択します。

7. 表示されたAPIキーをコピーします。

8. APIキーの制限を設定します。

   おすすめ:

   ```text
   APIの制限: YouTube Data API v3
   アプリケーションの制限: まずは「なし」
   ```

9. `.streamlit/secrets.toml` に保存します。

   ```toml
   YOUTUBE_API_KEY = "AIza..."
   ```

Google公式ドキュメントでは、YouTube Data APIを使うにはGoogleアカウント、Google Cloud/Developers Consoleのプロジェクト、APIの有効化、必要に応じたOAuth認証が必要と説明されています。  
参考: https://developers.google.com/youtube/v3/getting-started

---

## 6. OpenAI APIキーの取得方法

AI要約、タイトル案、サムネイル画像生成、英語音声の文字起こし・校正・日本語翻訳に必要です。YouTube上の既存字幕を取得するだけなら不要です。

1. OpenAI Platformを開きます。

   https://platform.openai.com/

2. APIキー画面を開きます。

   https://platform.openai.com/api-keys

3. APIキーを作成します。

4. Billing / 支払い設定を確認します。

   クレジットや利用枠がない場合、要約時に `insufficient_quota` や `429` エラーになります。

5. `.streamlit/secrets.toml` に保存します。

   ```toml
   OPENAI_API_KEY = "sk-..."
   ```

このアプリでは、要約・タイトル案・サムネイル生成の既定モデルは `gpt-5.5` です。アカウントで利用できない場合は、画面の「OpenAIモデル」欄で別のモデル名に変更してください。

OpenAI公式のクイックスタートでは、APIキーを作成してSDKからAPIを呼び出す流れが案内されています。  
参考: https://developers.openai.com/api/docs/quickstart

---

## 7. YouTubeアップロード用OAuthクライアントJSONの作成方法

YouTubeへ動画をアップロードするには、APIキーではなくOAuth認証が必要です。

この設定は少しだけ手順が多いです。

### 6.1 YouTube Data API v3を有効化する

YouTube Data APIキーを作ったプロジェクトと同じGoogle Cloudプロジェクトで問題ありません。

https://console.cloud.google.com/apis/library/youtube.googleapis.com

「有効」になっていることを確認してください。

### 6.2 OAuth同意画面を設定する

Google Cloud Consoleで次を開きます。

```text
APIとサービス
↓
OAuth同意画面
```

または、現在のUIでは次の名前になっていることがあります。

```text
Google Auth Platform
↓
Branding / Audience / Data Access
```

個人利用・テスト利用なら、まずはテスト状態で構いません。

「内部 / 外部」を聞かれた場合は、通常は次のように選びます。

```text
個人のGmailアカウントで使う場合: 外部
Google Workspace組織内だけで使う場合: 内部
```

`内部` は、基本的にGoogle Workspace組織の中のユーザーだけが使うアプリ向けです。
個人のGmailアカウントや、組織外のGoogleアカウントで認証する可能性がある場合は `外部` を選んでください。

設定の考え方:

- アプリ名: 任意
- ユーザーサポートメール: 自分のGoogleアカウント
- デベロッパー連絡先: 自分のメール
- スコープ: `Data Access` から追加します
- テストユーザー: `Audience` から追加します

重要: YouTubeへ投稿するチャンネルを管理できるGoogleアカウントをテストユーザーに入れてください。

このアプリが使うYouTubeアップロード用スコープは次です。

```text
https://www.googleapis.com/auth/youtube
```

スコープやテストユーザーが見当たらない場合は、まず `Branding` の基本情報作成を最後まで完了してください。
その後、左メニューまたは上部メニューに `Audience` と `Data Access` が表示されることがあります。

`外部` でテスト中の場合は、`Audience` の `Test users` に、実際にアップロード認証で使うGoogleアカウントを追加します。

`example@pages.plusgoogle.com` のようなBrand Account由来の内部的なアドレスは、通常のGoogleログイン用メールとしては使わないでください。
テストユーザーに追加するのは、実際にログインできるGmailまたはGoogle Workspaceアカウントです。

人から譲り受けたブランドチャンネルを使う場合は、そのブランドチャンネルの所有者または管理者になっている通常のGoogleアカウントでOAuth認証します。
可能であれば、前の所有者にYouTube StudioまたはBrand Account管理画面から自分の通常Googleアカウントを所有者として追加・移行してもらってください。
YouTubeの「チャンネル権限」で招待されたユーザーは、YouTube APIで使えない機能があるため、APIアップロードでは所有者アカウントでの認証が最も確実です。

例: `abc@gmail.com` でログインでき、その中に通常チャンネルと `xyz@pages.plusgoogle.com` 由来のブランドチャンネルがある場合、OAuthのテストユーザーには `abc@gmail.com` を追加します。
認証時は `abc@gmail.com` でログインし、YouTubeチャンネル選択画面が表示されたら、投稿したいブランドチャンネル側を選択してください。
もしアプリが通常チャンネル側に認証されてしまった場合は、`.streamlit/youtube_upload_token.json` を削除してから再認証します。
チャンネル選択画面が出ない、または毎回通常チャンネル側に入ってしまう場合は、YouTube側でそのGoogleアカウントの既定チャンネルをブランドチャンネルに変更してから再認証すると改善することがあります。

### 6.3 OAuthクライアントIDを作成する

Google Cloud Consoleで次を開きます。

```text
APIとサービス
↓
認証情報
↓
認証情報を作成
↓
OAuthクライアントID
```

アプリケーションの種類は、**必ず**次を選びます。

```text
デスクトップアプリ
```

「ウェブアプリケーション」で作ったJSONでは認証できません（`redirect_uri_mismatch` エラーになります）。
アプリ側でも、ウェブアプリケーション用のJSONはアップロード時に弾かれるようになっています。

すでに作ってしまった場合は、種類を「デスクトップアプリ」にして作り直してください。
手元のJSONをメモ帳で開いて、先頭が `{"installed":` ならデスクトップアプリ、`{"web":` ならウェブアプリケーションです。

作成後、JSONをダウンロードします。

ダウンロードしたJSONファイルを次の名前に変更して、この場所に置きます。

```text
<アプリを展開したフォルダ>\.streamlit\client_secret.json
```

### 6.4 Googleへのログイン（「未認証」のままになる場合）

**キーとJSONを保存しただけでは「ログイン状態」は「未認証」のままです。これは異常ではありません。**

「認証ファイル」と「ログイン状態」は別の項目です。

| 表示 | 意味 |
|---|---|
| 認証ファイル: 設定済み | OAuthクライアントJSONの保存が完了している |
| ログイン状態: 未認証 | まだGoogleにログインしていない（これから行う） |

「認証済み」にするには、次のどちらかを行います。

1. 「アカウント設定」ページの **「今すぐGoogleにログイン」** ボタンを押す（推奨）
2. または、そのまま初回のアップロードを実行する

どちらの場合もブラウザが開くので、アカウントを選んで「許可」まで進めてください。
完了すると表示が「認証済み」に変わります。

ここで選ぶアカウントはとても大事です。

選ぶべきアカウント:

- 投稿先YouTubeチャンネルの所有者
- または、そのチャンネルを管理できるGoogleアカウント

Brand Accountを使っている場合は、ログイン後のYouTube側で対象チャンネルに投稿されるか必ず非公開でテストしてください。

間違ったアカウントで認証してしまった場合は、次のファイルを削除してから再度アップロードしてください。

```text
.streamlit/youtube_upload_token.json
```

YouTube公式のアップロードガイドでは、動画アップロードにOAuth 2.0認証とクライアントシークレットファイルを使う流れが示されています。  
参考: https://developers.google.com/youtube/v3/guides/uploading_a_video

---

## 8. 検索・ダウンロードの使い方

1. アプリを起動します。

2. 検索キーワードを入力します。

3. 取得モードを選びます。

   ```text
   再生回数順
   人気順（関連度）
   バズり度順
   ```

4. 開始年・終了年を選びます。

5. 「検索」を押します。

6. 検索結果の表で、ダウンロードしたい動画にチェックを入れます。

7. 検索結果の下にある「動画の言語を選択」で「日本語動画」または「英語動画」を選びます。初期状態は「日本語動画」です。

「日本語動画」は従来どおり、指定した言語の字幕から文字起こしを作ります。

「英語動画」は、英語の手動字幕を優先し、なければ英語の自動字幕を取得します。どちらもない場合は、FFmpegで動画から音声を取り出し、OpenAI APIで英語の文字起こしを作ります。音声認識結果はAIで校正してから日本語へ翻訳し、FFmpegで動画へ字幕を表示します。

動画は、YouTubeが用意している最大1080pの形式を最初から選んでダウンロードします。4K動画をパソコン上で縮小する方式ではないため、保存容量と処理時間を抑えられます。特殊な動画で1080p以下の形式が提供されない場合だけ、利用できる形式へ自動的に切り替えます。

日本語字幕付き動画も、パソコンで滑らかに再生しやすいよう最大1920×1080で保存します。元動画が1080p以下の場合は拡大しません。

日本語字幕は、長すぎる文章を句読点・接続語・助詞などの文節で分割します。短すぎる字幕は前後へ統合し、英語の商品名やバージョン番号（例: `ChatGPT 5.6`）の途中では分割しません。画面内の改行も同じルールで最大2行に整えます。

音声認識APIを実際に確認する場合は、「YouTube字幕があっても音声から文字起こしする（テスト用）」をオンにできます。通常運用ではオフのままにしてください。オンにするとYouTube字幕があっても音声認識・AI校正を行うため、OpenAI APIの処理量と料金が増えます。

長い動画の音声は10分ごとに分割されます。処理途中のファイルも保存されるため、エラー後に再実行すると、完成済みの音声・文字起こし・校正結果を可能な範囲で再利用します。

一度動画保存まで成功した動画は、検索結果に「🔴 ダウンロード済み」の印付きで表示され続けます。字幕処理を再開したい場合は、その動画を選択して再度ダウンロード処理を実行してください。「再ダウンロード」をオンにしない限り元動画は取り直さず、保存済みの途中結果から処理を続けます。

8. 「ダウンロード後処理」を確認します。

おすすめ:

```text
YouTube字幕・自動字幕を取得して transcript.txt を作成する: ON
取得した文字起こしから要約・タイトル案を作成する: ON
要約をもとにサムネイル画像PNGを生成する: ON
```

OpenAI APIキーが未設定の場合は、動画保存と字幕取得だけ行われます。
後からOpenAI APIキーを設定すれば、アップロード画面で要約・タイトル案やサムネイルを作成できます。

9. 「選択した動画をダウンロード」を押します。

保存形式は次のようになります。

```text
downloads/
  動画タイトル [videoId]/
    video.mkv
    subtitle.ja.auto.vtt
    transcript.txt
    summary.md
    thumbnail.png
    thumbnail_prompt.txt
    upload_metadata.json
```

英語動画の場合は、同じフォルダに次のファイルも保存されます。

```text
subtitles_en.manual.vtt   # 英語の手動字幕の場合
subtitles_en.auto.vtt     # 英語の自動字幕の場合
transcript_en.txt
subtitles_ja.srt
video_ja_subtitled.mp4
```

YouTube字幕がなく、音声から文字起こしした場合は次のファイルも作られます。

```text
audio_chunks/                     # 10分ごとに分割した音声
transcription_en_raw.json         # 音声認識の再開用データ
subtitles_en_raw.srt              # 未修正の英語字幕
transcript_en_raw.txt             # 未修正の英語文字起こし
transcription_en_corrected.json   # AI校正の再開用データ
subtitles_en_corrected.srt        # AI校正済み英語字幕
transcript_en_corrected.txt       # AI校正済み英語文字起こし
```

途中で翻訳や字幕表示に失敗しても、ダウンロード済みの `video.mkv` と、それまでに作成できたファイルは削除されません。再度同じ動画の処理を実行すると、完成済みファイルは可能な範囲で再利用されます。

一度ダウンロードした動画は、同じ保存先フォルダを使っている限り、次回以降の検索結果に「🔴 ダウンロード済み」の印が付きます。

もう一度動画を取り直したい場合は、その動画を選択すると表示される
「ダウンロード済みの◯件を再ダウンロードする（動画ファイルを上書き）」をオンにしてから
ダウンロードボタンを押してください。オフのままなら動画はスキップされ、
字幕・要約などの後処理だけをやり直せます。

ダウンロードが終わると、処理した動画の「選択」チェックは自動で外れます。
失敗した動画だけはチェックが残るので、原因を直してそのままもう一度
ダウンロードボタンを押せば再実行できます。

---

## 9. 生成されるファイルの意味

| ファイル | 内容 |
|---|---|
| `video.mkv` | ダウンロードした動画 |
| `subtitle.ja.auto.vtt` | YouTube自動字幕 |
| `subtitle.ja.manual.vtt` | 投稿者が付けた字幕 |
| `transcript.txt` | 字幕から本文だけを取り出した文字起こし |
| `subtitles_en.manual.vtt` / `subtitles_en.auto.vtt` | 英語動画から取得した原文字幕 |
| `transcript_en.txt` | 英語原文字幕から作った文字起こし |
| `subtitles_en_raw.srt` / `transcript_en_raw.txt` | 音声認識直後の未修正データ |
| `subtitles_en_corrected.srt` / `transcript_en_corrected.txt` | 文脈を考慮してAI校正した英語データ |
| `transcription_en_raw.json` / `transcription_en_corrected.json` | 文字起こし・校正処理を途中から再開するためのデータ |
| `subtitles_ja.srt` | タイムコードを維持して日本語へ翻訳した字幕 |
| `video_ja_subtitled.mp4` | 日本語字幕を画面に表示したMP4動画 |
| `summary.md` | AI要約、タイトル案、サムネイル文言案 |
| `thumbnail.png` | AI生成サムネイル画像 |
| `thumbnail_prompt.txt` | サムネイル生成に使ったプロンプト |
| `thumbnail_upload.jpg` | 2MB超のサムネイルをアップロード用に圧縮した画像 |
| `upload_metadata.json` | 投稿準備・投稿結果の保存 |

`video_ja_subtitled.mp4` があるフォルダは、YouTubeアップロード画面でこの字幕付き動画が優先して選ばれます。

---

## 10. YouTubeアップロードの使い方

まずは必ず「非公開」でテストしてください。

1. 上部の「YouTubeアップロード」を開きます。

2. 「アップロードに使うアカウント / 設定プロファイル」を選びます。

   アカウント設定ページで登録したプロファイルから選択します。
   ここで選んだプロファイルのOAuth JSONとOAuthトークンを使ってアップロードします。

   表示されるステータス:

   ```text
   使用プロファイル
   認証ファイル: 設定済み / 未設定
   ログイン状態: 認証済み / 未認証
   ```

   「ログイン状態」が「未認証」の場合は、先に「アカウント設定」ページで
   「今すぐGoogleにログイン」を済ませておくと安心です（そのままアップロードしても、
   実行時にブラウザが開いて認証されます）。

   別チャンネルへ投稿したい場合は、必ずここで正しいプロファイルを選んでください。

3. 「アップロード対象フォルダ」を確認します。

   既定値:

   ```text
   ./downloads
   ```

4. 「投稿する動画セット」を選びます。

5. 要約やタイトル案がない場合は「要約・タイトル案を後から生成」を開きます。

   `transcript.txt` がある素材であれば、OpenAI APIキーを設定した後からでも生成できます。
   生成結果は `summary.md` に保存されます。

6. サムネイルプレビューを確認します。

7. サムネイルが気に入らない場合は「サムネイルだけ再生成」を開きます。

   `summary.md` または `transcript.txt` がある素材であれば、サムネイルだけを再生成できます。
   既存のサムネイルは上書きされ、再生成に使ったプロンプトも保存されます。

   保存先:

   ```text
   thumbnail.png
   thumbnail_prompt.txt
   ```

8. タイトル候補を選びます。

   `summary.md` の「新しい動画タイトル案」から自動で候補が読み込まれます。

9. 投稿タイトルを必要に応じて編集します。

10. 説明欄を確認します。

   構成は次の通りです。

   ```text
   毎回入れたい固定文章

   生成要約文

   ハッシュタグ
   ```

11. 固定文章を入力します。

   例:

   ```text
   ▼無料講座はこちら
   https://example.com

   ▼公式LINEはこちら
   https://example.com/line

   ※本動画は情報提供を目的としており、投資助言ではありません。
   ```

12. 固定文章を毎回使いたい場合は「固定文章テンプレートを保存」を押します。

   保存先:

   ```text
   .streamlit/upload_description_template.txt
   ```

13. 説明欄ハッシュタグを確認します。

    例:

    ```text
    #FX #トレード #スキャルピング
    ```

14. 動画タグを確認します。

    例:

    ```text
    FX, トレード, スキャルピング, 投資
    ```

15. 公開設定を選びます。

    最初は必ずこれがおすすめです。

    ```text
    非公開
    ```

    予約公開したい場合は、公開設定で「予約公開」を選び、公開したい日付・時刻を入力します。
    予約公開では、アップロード直後は非公開で保存され、指定時刻になると公開されます。

16. 「プレビュー表示」を押して、実際に使われる投稿内容を確認します。

    プレビューには、次の内容が反映されます。

    ```text
    実際に使うタイトル
    最終説明欄
    タグ
    公開設定
    ```

    タイトル候補を選んだだけで投稿タイトル欄を手動編集していない場合は、選択中のタイトル候補が使われます。
    投稿タイトル欄を手動編集した場合は、その手動編集したタイトルが優先されます。

    コメント欄のON/OFF、収益化、終了画面、カード、字幕、詳細な年齢制限や視聴者設定など、このツールで設定できない項目はアップロード後にYouTube Studioで手動確認・設定してください。

17. 必要な場合だけ「詳細設定（通常は変更不要）」を確認します。

    通常は、手順2で選んだプロファイルの認証情報が自動で入るため、変更する必要はありません。

18. 「YouTubeに非公開/設定どおりアップロード」を押します。

19. 初回だけGoogleログイン画面が開きます。

20. 投稿先チャンネルを管理できるGoogleアカウントでログインします。

21. アップロード完了後、動画URLが表示されます。

YouTube APIの `videos.insert` は動画作成に使われ、`thumbnails.set` は動画サムネイル設定に使われます。  
参考:

- https://developers.google.com/youtube/v3/docs/videos/insert
- https://developers.google.com/youtube/v3/docs/thumbnails/set

---

## 11. どのアカウントを使えばよいか

### Google Cloud Consoleで使うアカウント

基本的には、あなたが管理しやすいGoogleアカウントでOKです。

おすすめ:

```text
YouTubeチャンネルを管理しているGoogleアカウント
```

理由:

- APIキー管理が分かりやすい
- OAuthテストユーザー設定が分かりやすい
- アップロード先チャンネルとの関係が混乱しにくい

### OAuthログインで使うアカウント

これは必ず投稿先YouTubeチャンネルを管理できるアカウントにしてください。

違うアカウントでログインすると、意図しないチャンネルに投稿されたり、投稿権限がなく失敗したりします。

### OpenAIで使うアカウント

OpenAI APIの支払い・利用枠を管理するアカウントです。Googleアカウントと同じである必要はありません。

---

## 12. よくあるトラブル

### まず「環境チェック」を見る

「アカウント設定」ページの一番上に **「環境チェック」** があります。
ダウンロードや認証がうまくいかないときは、まずここを開いてください。

チェックする内容:

| 項目 | 内容 |
|---|---|
| yt-dlp | ダウンロード本体。古いと必ず失敗します |
| ffmpeg | 映像と音声の結合。無いとダウンロードは必ず失敗します |
| Deno | YouTubeの再生制限の解除に使用。無いと一部の動画が403になります |
| ツールの場所 | パスが長すぎると保存に失敗します |
| 保存先への書き込み | 保存先フォルダに書き込めるか |
| 空き容量 | ディスクの残量 |

❌が付いた項目を先に解消してください。
サポートに連絡するときは、**この画面のスクリーンショット**を添えると原因を特定しやすくなります。

### ダウンロードが失敗する

**原因の1位は「yt-dlp が古い」です。**

YouTubeは仕様変更が頻繁なため、古い yt-dlp では
`HTTP Error 403` / `Requested format is not available` / `Sign in to confirm you're not a bot`
といったエラーで失敗します。

「環境チェック」の yt-dlp に❌が付いていたら、アプリを閉じてから次を実行してください。

Windows（コマンドプロンプト）:

```text
cd /d "<アプリを展開したフォルダ>"
.runtime\python312\python.exe -m pip install -U yt-dlp
```

macOS（ターミナル）:

```text
cd "<アプリを展開したフォルダ>"
.runtime/venv/bin/python -m pip install -U yt-dlp
```

その他の原因:

| 症状 | 原因と対処 |
|---|---|
| すべての動画で失敗する | yt-dlp が古い / ffmpeg が無い。環境チェックを確認 |
| 特定の動画だけ失敗する | 非公開・メンバー限定・年齢制限・地域制限の動画。このツールでは取得できません |
| `Sign in to confirm you're not a bot` | VPN・社内プロキシ・共有回線が原因。時間をおくか回線を変えてください |
| 長いタイトルの動画だけ失敗する | Windowsのパス長制限。ツール本体を `C:\ytool` のような浅いフォルダへ移動してください |
| 「動画は既に保存済みでした」と出る | 失敗ではありません。取り直したい場合は「再ダウンロード」をオンにしてください |

必ず `start_app.bat`（またはデスクトップのショートカット）から起動してください。
別の方法で起動すると ffmpeg や Deno が見つからず、ダウンロードが失敗することがあります。

まれに、更新した直後の yt-dlp 自体に不具合があることがあります。
「更新したら逆に動かなくなった」場合は、1つ前の安定バージョンに固定できます
（バージョン番号は https://github.com/yt-dlp/yt-dlp/releases で確認できます）。

```text
.runtime\python312\python.exe -m pip install yt-dlp==<1つ前のバージョン番号>
```

### YouTube検索で403エラーが出る

考えられる原因:

- YouTube Data API v3が有効になっていない
- APIキーが間違っている
- APIキー制限が厳しすぎる
- クォータ上限に達した

確認場所:

```text
Google Cloud Console
↓
APIとサービス
↓
YouTube Data API v3
↓
割り当て / Quotas
```

### OpenAI要約で429 / insufficient_quota が出る

OpenAI APIの利用枠または課金設定の問題です。

確認場所:

```text
OpenAI Platform
↓
Billing
```

### `client_secret.json` がないと言われる

`.streamlit/client_secret.json` が存在するか確認してください。

パス:

```text
<アプリを展開したフォルダ>\.streamlit\client_secret.json
```

### 「ログイン状態」が「未認証」のまま変わらない

まず、**キーとJSONを保存しただけでは「未認証」のままが正常**です。
「アカウント設定」ページの「今すぐGoogleにログイン」を押してください（詳細は 6.4）。

ボタンを押しても認証できない場合:

| エラー表示 | 原因と対処 |
|---|---|
| `redirect_uri_mismatch` | OAuthクライアントの種類が「ウェブアプリケーション」になっています。「デスクトップアプリ」で作り直してください |
| `access_denied` / 「確認プロセスが完了していません」 | OAuth同意画面が「テスト中」で、テストユーザーに未登録です。使用するGoogleアカウントを追加してください |
| `has not been used in project` | そのプロジェクトで YouTube Data API v3 が有効化されていません |
| ブラウザが開かない | 既定のブラウザ設定と、セキュリティソフトのファイアウォールを確認してください |

「認証ファイル」が「未設定」のままの場合は、アップロード画面で選んでいる**プロファイル**が、
JSONを保存したプロファイルと同じか確認してください。
プロファイルごとに保存先が分かれています（設定画面下部の「このプロファイルの保存先」で実際のパスを確認できます）。

### 間違ったGoogleアカウントで認証した

「アカウント設定」ページの「ログインをやり直す」ボタンを押してください。
手動で削除する場合は次のファイルです。

```text
.streamlit/youtube_upload_token.json
```

### サムネイル設定に失敗する

考えられる原因:

- 画像が2MBを超えている
- チャンネル側のサムネイル設定権限がない
- YouTube側の一時的な制限

このアプリは2MB超の場合 `thumbnail_upload.jpg` に圧縮しますが、それでも失敗する場合はYouTube Studioで手動設定してください。

### 投稿した動画が公開できない

Google CloudプロジェクトやYouTube APIの状態によっては、未確認アプリからアップロードした動画が非公開に制限される場合があります。まずは非公開でテストし、公開運用する場合はGoogle/YouTube側の要件を確認してください。

---

## 13. 配布先PCで使う場合

配布用ZIPは `dist` フォルダにあります。

```text
Windows向け:
dist\YouTube-Search-Downloader.zip

macOS向け:
dist\YouTube-Search-Downloader-mac.zip
```

配布ZIPには以下は含まれません。

```text
.runtime/
downloads/
.streamlit/secrets.toml
.streamlit/settings_profiles.json
.streamlit/profiles/
.streamlit/client_secret.json
.streamlit/youtube_upload_token.json
```

別PCで使う場合は、そのPCのアプリ画面で「アカウント設定」を開き、次を設定してください。

```text
YouTube Data API v3キー
OpenAI APIキー
OAuthクライアントJSON
```

Windowsでは、ZIPを展開して `start_app.bat` をダブルクリックします。
初回起動時に、ポータブルPython、Pythonパッケージ、ffmpeg、Denoが `.runtime` に自動で準備されます。

macOSでは、ZIPを展開して `start_app_macos.command` をダブルクリックします。
初回起動時に、Python仮想環境、Pythonパッケージ、ffmpegが `.runtime` に自動で準備されます。
macOSで「開発元を確認できない」などの警告が出る場合は、Finderで右クリックして「開く」を選んでください。

macOS版はMacに `python3` が入っていることが前提です。
`python3` がない場合は、先にPython 3をインストールしてください。

---

## 14. 安全な運用のおすすめ

- 最初の投稿は必ず「非公開」
- アップロード後、YouTube Studioでタイトル・説明欄・サムネイル・コメント設定を確認
- 他人の動画を無許可で再投稿しない
- APIキーやOAuth JSONを他人に渡さない
- 配布ZIPに `.streamlit` や `downloads` を含めない
- 固定文章には、必要に応じて免責事項を入れる

投資・FX系の動画では、説明欄に次のような注意書きを入れるのがおすすめです。

```text
※本動画は情報提供を目的としており、投資助言ではありません。
※投資にはリスクがあります。最終判断はご自身の責任で行ってください。
```

---

## 15. 参考公式ドキュメント

- YouTube Data API Overview  
  https://developers.google.com/youtube/v3/getting-started
- YouTube Data API - Upload a Video  
  https://developers.google.com/youtube/v3/guides/uploading_a_video
- YouTube Data API - videos.insert  
  https://developers.google.com/youtube/v3/docs/videos/insert
- YouTube Data API - thumbnails.set  
  https://developers.google.com/youtube/v3/docs/thumbnails/set
- OpenAI API Quickstart  
  https://developers.openai.com/api/docs/quickstart
