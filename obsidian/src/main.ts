import {
  App,
  Component,
  Editor,
  MarkdownRenderer,
  Modal,
  Notice,
  Plugin,
  PluginSettingTab,
  Setting,
  requestUrl,
} from "obsidian";

import { askVault, buildRequest, QueryError, toCallout, type QueryResponse, type Scope, type Transport } from "./query";

interface Settings {
  backendUrl: string;
  scope: Scope;
}

const DEFAULT_SETTINGS: Settings = {
  backendUrl: "http://127.0.0.1:8000",
  scope: "notes",
};

// requestUrl, not fetch: the backend's CORS list only admits the Next.js
// frontend on :3000, and requestUrl goes through Obsidian's native layer.
const transport: Transport = (req) =>
  requestUrl(req).then((r) => ({ status: r.status, text: r.text }));

export default class NightAtlasAsk extends Plugin {
  settings: Settings = DEFAULT_SETTINGS;

  async onload() {
    this.settings = Object.assign({}, DEFAULT_SETTINGS, await this.loadData());
    this.addSettingTab(new AskSettingTab(this.app, this));

    this.addCommand({
      id: "ask",
      name: "Ask vault",
      editorCallback: (editor) => this.prompt(editor.getSelection(), editor),
      callback: () => this.prompt(""),
    });

    this.addCommand({
      id: "ask-about-current-note",
      name: "Ask about current note",
      checkCallback: (checking) => {
        const file = this.app.workspace.getActiveFile();
        if (!file || file.extension !== "md") return false;
        if (!checking) this.prompt("", this.app.workspace.activeEditor?.editor ?? undefined, [file.path]);
        return true;
      },
    });
  }

  async saveSettings() {
    await this.saveData(this.settings);
  }

  private prompt(initial: string, editor?: Editor, contextNodes?: string[]) {
    new QuestionModal(this.app, initial, contextNodes, (question) =>
      this.ask(question, editor, contextNodes),
    ).open();
  }

  private async ask(question: string, editor?: Editor, contextNodes?: string[]) {
    const notice = new Notice("Asking Night Atlas…", 0);
    try {
      const res = await askVault(
        transport,
        this.settings.backendUrl,
        buildRequest(question, this.settings.scope, contextNodes),
      );
      new AnswerModal(this.app, question, res, editor).open();
    } catch (err) {
      new Notice(err instanceof QueryError ? err.message : `Night Atlas: ${String(err)}`, 8000);
    } finally {
      notice.hide();
    }
  }
}

class QuestionModal extends Modal {
  constructor(
    app: App,
    private initial: string,
    private contextNodes: string[] | undefined,
    private onSubmit: (question: string) => void,
  ) {
    super(app);
  }

  onOpen() {
    this.titleEl.setText(this.contextNodes ? `Ask about ${this.contextNodes[0]}` : "Ask your vault");
    const input = this.contentEl.createEl("textarea", {
      attr: { rows: "4", placeholder: "What do my notes say about…" },
    });
    input.style.width = "100%";
    input.value = this.initial;
    const submit = () => {
      const question = input.value.trim();
      if (!question) return;
      this.close();
      this.onSubmit(question);
    };
    input.addEventListener("keydown", (e) => {
      if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) submit();
    });
    new Setting(this.contentEl).addButton((b) => b.setButtonText("Ask").setCta().onClick(submit));
    input.focus();
  }

  onClose() {
    this.contentEl.empty();
  }
}

class AnswerModal extends Modal {
  // Owns the rendered answer's child components so they unload with the modal.
  private renderer = new Component();

  constructor(
    app: App,
    private question: string,
    private res: QueryResponse,
    private editor?: Editor,
  ) {
    super(app);
  }

  onOpen() {
    this.titleEl.setText(this.question);
    this.renderer.load();
    const body = this.contentEl.createDiv();
    MarkdownRenderer.render(this.app, this.res.answer, body, "", this.renderer);

    if (this.res.sources.length) {
      this.contentEl.createEl("h4", { text: "Sources" });
      const list = this.contentEl.createEl("ul");
      for (const src of this.res.sources) {
        const link = list.createEl("li").createEl("a", { text: src.title, href: "#" });
        link.addEventListener("click", (e) => {
          e.preventDefault();
          this.close();
          this.app.workspace.openLinkText(src.source, "");
        });
      }
    }

    const buttons = new Setting(this.contentEl);
    if (this.editor) {
      const editor = this.editor;
      buttons.addButton((b) =>
        b.setButtonText("Insert into note").onClick(() => {
          editor.replaceRange("\n" + toCallout(this.question, this.res), editor.getCursor("to"));
          this.close();
        }),
      );
    }
    buttons.addButton((b) =>
      b.setButtonText("Copy").onClick(async () => {
        await navigator.clipboard.writeText(toCallout(this.question, this.res));
        new Notice("Answer copied.");
      }),
    );
  }

  onClose() {
    this.renderer.unload();
    this.contentEl.empty();
  }
}

class AskSettingTab extends PluginSettingTab {
  constructor(app: App, private plugin: NightAtlasAsk) {
    super(app, plugin);
  }

  display() {
    const { containerEl } = this;
    containerEl.empty();

    new Setting(containerEl)
      .setName("Backend URL")
      .setDesc("Where the Night Atlas FastAPI backend listens. The command calls POST /api/query on it.")
      .addText((t) =>
        t
          .setPlaceholder(DEFAULT_SETTINGS.backendUrl)
          .setValue(this.plugin.settings.backendUrl)
          .onChange(async (value) => {
            this.plugin.settings.backendUrl = value.trim() || DEFAULT_SETTINGS.backendUrl;
            await this.plugin.saveSettings();
          }),
      );

    new Setting(containerEl)
      .setName("Search scope")
      .setDesc("Written notes only, exported AI chat transcripts, or both.")
      .addDropdown((d) =>
        d
          .addOptions({ notes: "Notes", chats: "Chats", all: "All" })
          .setValue(this.plugin.settings.scope)
          .onChange(async (value) => {
            this.plugin.settings.scope = value as Scope;
            await this.plugin.saveSettings();
          }),
      );
  }
}
