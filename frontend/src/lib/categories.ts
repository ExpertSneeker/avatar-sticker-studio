import {createContext,useContext} from 'react'
export type LibraryCategory={id:string;name:string}
export const DEFAULT_CATEGORIES:LibraryCategory[]=[{id:'boy',name:'男孩'},{id:'girl',name:'女孩'},{id:'animal',name:'动物'},{id:'general',name:'通用'}]
export const CategoryContext=createContext<{categories:LibraryCategory[];refresh:()=>void}>({categories:DEFAULT_CATEGORIES,refresh:()=>{}})
export const useCategories=()=>useContext(CategoryContext)
export function categoryName(categories:LibraryCategory[],id:string){return categories.find(c=>c.id===id)?.name||id}
