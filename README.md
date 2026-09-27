# SEVEN GODS DIVINE RUN

SEVEN GODSのキャラクター世界を使った、1プレイ約60〜120秒の2Dローグゴルフ試作です。

ボールを引いて離すだけの操作に、7柱の「加護」、壁反射、GOD LINE、DIVINE SHOTを組み合わせています。

> 現在はV0.1のUnityソース公開準備版です。正式なキャラクター画像・音源・完成シーンは権利確認と実機調整後に追加します。

## 現在の実装

- 3固定ホール
- マウス／1本指ドラッグショット
- 軌道予測、壁反射、OB、カップ判定
- 7種類の加護と3択
- GOD LINE、DIVINE SHOT、スコア
- タイトル、GOD選択、初回チュートリアル
- 結果画面、設定、Safe Area
- ローカルプレイ計測、デバッグ表示、ビルド検証
- WebGLビルドとGitHub Pages公開の受け皿

## リポジトリ構成

```text
Assets/                 Unityへ導入するコード
Assets/Editor/          Validator・WebGLビルド
docs/                   導入・公開手順
webgl/                  GitHub Pagesへ配信するWebGL出力先
PLAYTEST_CHECKLIST.md    10人テスト項目
V01_RELEASE_CHECKLIST.md リリース前確認
```

## Unityへの導入

1. Unity 6の2Dプロジェクトを作成します。
2. このリポジトリの`Assets`をプロジェクトへコピーします。
3. [Unityセットアップ手順](docs/UNITY_SETUP.md)に沿ってシーンを構成します。
4. `Tools > Seven Gods > Validate V0.1`を実行します。
5. Console Errorが0件であることを確認します。

## WebGLをローカル出力

1. Build Settingsへゲームシーンを登録します。
2. `Tools > Seven Gods > Build WebGL for GitHub Pages`を実行します。
3. `webgl/`に生成された内容をcommitしてmainへpushします。
4. GitHub ActionsがPagesへ自動配信します。

詳細は[WebGL公開手順](docs/WEBGL_PUBLISH.md)を参照してください。

## 操作

- ボールから逆方向へドラッグ
- 指またはマウスを離してショット
- 才華の加護取得時は飛行中に1回タップ
- Development BuildではF1または4本指タップでデバッグ表示

## 権利とライセンス

公開されていることは、キャラクターIP・画像・音源・名称の利用許諾を意味しません。現段階ではオープンソースライセンスを設定していません。利用前に[権利・ライセンス注意事項](LICENSE_NOTICE.md)を確認してください。

## 状態

`V0.1 / Internal playtest ready`

正式公開前に、Unity上のコンパイル、スマホ実機、WebGLブラウザでの検証が必要です。
