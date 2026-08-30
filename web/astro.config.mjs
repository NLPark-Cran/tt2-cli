// @ts-check
import { defineConfig } from 'astro/config';
import tailwindcss from '@tailwindcss/vite';

// 纯静态输出：astro build → dist/ 由 nginx 直接分发
export default defineConfig({
  site: 'https://lhub.tt2.li',
  output: 'static',
  vite: {
    plugins: [tailwindcss()],
  },
});
