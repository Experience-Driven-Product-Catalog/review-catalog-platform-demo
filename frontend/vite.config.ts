import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'
export default defineConfig({ plugins:[react(),tailwindcss()], base:'/review-catalog-platform-demo/', server:{port:5173} })
