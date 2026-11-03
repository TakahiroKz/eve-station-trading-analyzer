import { existsSync, mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import { resolve } from 'node:path'
import react from '@vitejs/plugin-react'
import { defineConfig, loadEnv, type Plugin } from 'vite'
import { de } from './src/i18n/de'
import { en } from './src/i18n/en'
import { es } from './src/i18n/es'
import { fr } from './src/i18n/fr'
import { it } from './src/i18n/it'
import { DEFAULT_LANG, LANGS, LOCALES, langPath, type Lang } from './src/i18n/langs'

const SITE = 'https://evemarket-analyzer.online'
const DICTS: Record<Lang, Record<string, string>> = { en, es, de, fr, it }

const escapeHtml = (text: string) =>
  text.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;')

const pageUrl = (lang: Lang) => `${SITE}${langPath(lang)}`
const manifestPath = (lang: Lang) => (lang === DEFAULT_LANG ? '/manifest.json' : `${langPath(lang)}manifest.json`)

/** `<link rel="alternate" hreflang>` for every language, the same block on every page. */
function hreflangTags(): string {
  const tags = LANGS.map(({ code }) => `<link rel="alternate" hreflang="${code}" href="${pageUrl(code)}" />`)
  tags.push(`<link rel="alternate" hreflang="x-default" href="${pageUrl(DEFAULT_LANG)}" />`)
  return tags.join('\n    ')
}

/** The text crawlers that do not run JavaScript get, built from the same dictionary keys the
 *  visible page uses so it can never drift from it. */
function noscriptBlock(lang: Lang): string {
  const d = DICTS[lang]
  const text = (key: string) => escapeHtml(d[key] ?? en[key as keyof typeof en])
  const steps = [1, 2, 3].map((n) => `<h3>${text(`how.step${n}.title`)}</h3><p>${text(`how.step${n}.body`)}</p>`)
  const states = ['POTENCIAL', 'POTENCIAL_SIN_ORDENES', 'EN_OBSERVACION', 'DESCARTADO'].map(
    (status) => `<h3>${text(`tab.${status}`)}</h3><p>${text(`how.stateBody.${status}`)}</p>`,
  )
  const languageLinks = LANGS.map(({ code, label }) => `<a href="${langPath(code)}">${label}</a>`).join(' · ')
  return [
    `<h1>${text('hero.title')}</h1>`,
    `<p>${text('hero.subtitle')}</p>`,
    `<p><a href="/items">${text('nav.allItems')}</a></p>`,
    `<h2>${text('how.title')}</h2>`,
    ...steps,
    `<h2>${text('how.statesTitle')}</h2>`,
    ...states,
    `<p>${text('footer.disclaimer')}</p>`,
    `<p>${languageLinks}</p>`,
  ].join('\n      ')
}

/** Fill the language placeholders of `index.html` (see the SEO_ tokens there). */
function renderPage(template: string, lang: Lang): string {
  const d = DICTS[lang]
  const fill: Record<string, string> = {
    '%SEO_LANG%': lang,
    '%SEO_TITLE%': escapeHtml(d['meta.title']),
    '%SEO_DESCRIPTION%': escapeHtml(d['meta.description']),
    '%SEO_OG_DESCRIPTION%': escapeHtml(d['meta.ogDescription']),
    '%SEO_CANONICAL%': pageUrl(lang),
    '%SEO_LOCALE%': LOCALES[lang].replace('-', '_'),
    '%SEO_MANIFEST%': manifestPath(lang),
    '<!--SEO_HREFLANG-->': hreflangTags(),
    '<!--SEO_NOSCRIPT-->': noscriptBlock(lang),
  }
  return Object.entries(fill).reduce((html, [token, value]) => html.split(token).join(value), template)
}

/** One real HTML page per language (`/es/`, `/de/`...) with its own title, description,
 *  canonical and hreflang, plus a localized manifest, so each language can be indexed. The
 *  default language is `index.html` itself. The app picks the language from the path. */
function languagePages(): Plugin {
  let template = ''
  let outDir = 'dist'
  let root = process.cwd()
  let isBuild = false

  return {
    name: 'language-pages',
    configResolved(config) {
      outDir = resolve(config.root, config.build.outDir)
      root = config.root
      isBuild = config.command === 'build'
    },
    transformIndexHtml: {
      order: 'post',
      handler(html, ctx) {
        template = html
        // In dev the same index.html answers `/es/` too: render the language of the URL.
        const first = (ctx.originalUrl ?? '/').split('?')[0].split('/')[1]
        const lang = LANGS.find(({ code }) => code === first)?.code ?? DEFAULT_LANG
        return renderPage(html, lang)
      },
    },
    closeBundle() {
      if (!isBuild || !template) return
      const baseManifest = JSON.parse(readFileSync(resolve(root, 'public/manifest.json'), 'utf8'))
      for (const { code } of LANGS) {
        if (code === DEFAULT_LANG) continue
        const dir = resolve(outDir, code)
        if (!existsSync(dir)) mkdirSync(dir, { recursive: true })
        writeFileSync(resolve(dir, 'index.html'), renderPage(template, code))
        const manifest = {
          ...baseManifest,
          lang: code,
          description: DICTS[code]['meta.description'],
          start_url: langPath(code),
        }
        writeFileSync(resolve(dir, 'manifest.json'), JSON.stringify(manifest, null, 2) + '\n')
      }
    },
  }
}

// https://vite.dev/config/
export default defineConfig(({ mode }) => {
  // `API_PROXY` (in an untracked frontend/app/.env) points the dev server at another backend,
  // e.g. the production one, to work on the UI without running the API locally.
  const env = loadEnv(mode, process.cwd(), '')
  return {
    plugins: [react(), languagePages()],
    server: {
      proxy: {
        '/api': { target: env.API_PROXY || 'http://localhost:8001', changeOrigin: true },
      },
    },
  }
})
