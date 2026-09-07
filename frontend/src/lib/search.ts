/** Whitespace-separated terms all match, in any order and regardless of case. */
export function searchMatcher(query: string): (text: string) => boolean {
  const terms = query.normalize('NFKC').toLocaleLowerCase().trim().split(/\s+/u).filter(Boolean)
  return text => {
    const normalized = text.normalize('NFKC').toLocaleLowerCase()
    return terms.every(term => normalized.includes(term))
  }
}
