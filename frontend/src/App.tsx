import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import { Layout } from './components/Layout'
import { ToastProvider } from './components/Toast'
import { BookOverviewPage } from './pages/BookOverviewPage'
import { BooksPage } from './pages/BooksPage'
import { ReviewPage } from './pages/ReviewPage'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: { retry: 1, refetchOnWindowFocus: false },
  },
})

export default function App() {
  return (
    <QueryClientProvider client={queryClient}>
      <ToastProvider>
        <BrowserRouter>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/" element={<BooksPage />} />
              <Route path="/books/:id" element={<BookOverviewPage />} />
              <Route path="/books/:id/review" element={<ReviewPage />} />
              <Route path="*" element={<div className="text-sm text-gray-600">Page not found.</div>} />
            </Route>
          </Routes>
        </BrowserRouter>
      </ToastProvider>
    </QueryClientProvider>
  )
}
