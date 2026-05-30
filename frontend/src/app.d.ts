declare global {
  namespace App {
    interface User {
      id: string;
      username: string;
      is_admin: boolean;
      permissions: Record<string, unknown>;
    }
    interface Locals {
      user: User | null;
    }
    interface PageData {
      user?: User | null;
    }
  }
}

export {};
