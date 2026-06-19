declare module 'chromadb' {
  export class Client {
    constructor(options: { url: string });
    getOrCreateCollection(params: { name: string }): Promise<any>;
  }
  export type Collection = any;
}
