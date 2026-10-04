import { useState } from 'react'

// Write endpoints need the server's API_KEY. It is kept in this browser only
// (same storage key as the /label page) and sent as X-API-Key.
const STORAGE_KEY = 'proxylens.apiKey'

function read(): string {
  try {
    return localStorage.getItem(STORAGE_KEY) ?? ''
  } catch {
    return ''
  }
}

export function useApiKey(): [string, (value: string) => void] {
  const [key, setKey] = useState(read)
  const update = (value: string) => {
    setKey(value)
    try {
      localStorage.setItem(STORAGE_KEY, value)
    } catch {
      // storage blocked (private mode): the key lasts for this page only
    }
  }
  return [key, update]
}
