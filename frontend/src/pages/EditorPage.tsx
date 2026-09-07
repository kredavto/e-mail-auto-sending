import { EmailEditor } from "../components/editor/EmailEditor";

export function EditorPage() {
  return (
    <main className="mx-auto max-w-[1480px] px-4 py-6 sm:px-8 sm:py-10">
      <header className="mb-8 flex flex-col gap-5 border-b border-ink/15 pb-7 md:flex-row md:items-end md:justify-between">
        <div><p className="mb-2 text-xs font-semibold uppercase tracking-[.22em] text-clay">Premium B2B Mailer / Studio</p><h1 className="m-0 max-w-3xl font-display text-4xl font-bold leading-[1.05] tracking-tight sm:text-6xl">Письмо, которое выглядит лично.</h1></div>
        <div className="flex items-center gap-3"><span className="h-2.5 w-2.5 rounded-full bg-acid ring-4 ring-acid/25"/><span className="text-sm font-medium">Черновик · Сайты premium</span></div>
      </header>
      <EmailEditor />
    </main>
  );
}

