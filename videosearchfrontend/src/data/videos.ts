export interface Video {
  id: string
  title: string
  channel: string
  category: string
  duration: string
  views: number
  publishedDaysAgo: number
  /** seed used to generate a stable demo thumbnail/avatar via picsum.photos */
  seed: string
}

export const CATEGORIES = [
  'All',
  'JavaScript',
  'React',
  'AI',
  'Design',
  'Music',
  'Travel',
  'Cooking',
] as const

export const HOT_SEARCHES = [
  'typescript',
  'react 19',
  'neural networks',
  'lofi',
  'ramen',
  'css grid',
]

export const VIDEOS: Video[] = [
  {
    id: 'v1',
    title: 'Build a Video Search Engine with TypeScript — Full Walkthrough',
    channel: 'CodeCraft',
    category: 'JavaScript',
    duration: '24:12',
    views: 2_400_000,
    publishedDaysAgo: 3,
    seed: 'codecraft-ts',
  },
  {
    id: 'v2',
    title: 'React 19 New Features Explained with Live Examples',
    channel: 'Frontend Focus',
    category: 'React',
    duration: '18:47',
    views: 1_150_000,
    publishedDaysAgo: 9,
    seed: 'react19',
  },
  {
    id: 'v3',
    title: 'Neural Networks from Scratch in 20 Minutes',
    channel: 'AI Academy',
    category: 'AI',
    duration: '20:05',
    views: 890_000,
    publishedDaysAgo: 2,
    seed: 'nn-scratch',
  },
  {
    id: 'v4',
    title: 'Lofi Beats to Code To — 24/7 Chill Mix',
    channel: 'Chill Vibes',
    category: 'Music',
    duration: '1:04:22',
    views: 12_300_000,
    publishedDaysAgo: 14,
    seed: 'lofi-247',
  },
  {
    id: 'v5',
    title: '5 Hidden Gems in Japan You Must Visit (2026)',
    channel: 'Wanderlust Diaries',
    category: 'Travel',
    duration: '14:33',
    views: 620_000,
    publishedDaysAgo: 6,
    seed: 'japan-gems',
  },
  {
    id: 'v6',
    title: 'The Perfect Ramen at Home — Chef Secrets Revealed',
    channel: 'Umami Kitchen',
    category: 'Cooking',
    duration: '12:08',
    views: 3_800_000,
    publishedDaysAgo: 11,
    seed: 'ramen-home',
  },
  {
    id: 'v7',
    title: 'TypeScript Tips: 10 Tricks You Wish You Knew Earlier',
    channel: 'CodeCraft',
    category: 'JavaScript',
    duration: '10:26',
    views: 1_900_000,
    publishedDaysAgo: 1,
    seed: 'ts-tips',
  },
  {
    id: 'v8',
    title: 'CSS Grid vs Flexbox — When to Use What',
    channel: 'Pixel Perfect',
    category: 'Design',
    duration: '15:44',
    views: 740_000,
    publishedDaysAgo: 19,
    seed: 'grid-flex',
  },
  {
    id: 'v9',
    title: 'How Transformers Actually Work (Fully Illustrated)',
    channel: 'AI Academy',
    category: 'AI',
    duration: '32:51',
    views: 5_600_000,
    publishedDaysAgo: 27,
    seed: 'transformers',
  },
  {
    id: 'v10',
    title: 'Vite 9 — The New Build Tool Every Dev Should Know',
    channel: 'Frontend Focus',
    category: 'React',
    duration: '09:17',
    views: 480_000,
    publishedDaysAgo: 4,
    seed: 'vite9',
  },
  {
    id: 'v11',
    title: 'Solo Travel Packing Guide — Carry-On Only',
    channel: 'Wanderlust Diaries',
    category: 'Travel',
    duration: '11:59',
    views: 310_000,
    publishedDaysAgo: 33,
    seed: 'packing',
  },
  {
    id: 'v12',
    title: 'Dark Mode UI Design — Principles & Anti-Patterns',
    channel: 'Pixel Perfect',
    category: 'Design',
    duration: '16:20',
    views: 265_000,
    publishedDaysAgo: 8,
    seed: 'darkmode',
  },
]

export function formatViews(views: number): string {
  if (views >= 1_000_000) {
    return `${(views / 1_000_000).toFixed(1).replace(/\.0$/, '')}M views`
  }
  if (views >= 1_000) {
    return `${(views / 1_000).toFixed(1).replace(/\.0$/, '')}K views`
  }
  return `${views} views`
}

export function timeAgo(days: number): string {
  if (days < 1) return 'Today'
  if (days === 1) return 'Yesterday'
  if (days < 7) return `${days} days ago`
  if (days < 30) return `${Math.floor(days / 7)} week${Math.floor(days / 7) > 1 ? 's' : ''} ago`
  if (days < 365) return `${Math.floor(days / 30)} month${Math.floor(days / 30) > 1 ? 's' : ''} ago`
  return `${Math.floor(days / 365)} year${Math.floor(days / 365) > 1 ? 's' : ''} ago`
}

export function thumbUrl(seed: string): string {
  return `https://picsum.photos/seed/${seed}/640/360`
}

export function avatarUrl(seed: string): string {
  return `https://picsum.photos/seed/${seed}-av/96/96`
}
