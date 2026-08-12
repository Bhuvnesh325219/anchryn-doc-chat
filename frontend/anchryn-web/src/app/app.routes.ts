import { Routes } from '@angular/router';

import { Chat } from './chat/chat';
import { SignIn } from './sign-in/sign-in';
import { anonymousGuard, authGuard } from './services/auth-guard';

export const routes: Routes = [
  { path: '', component: Chat, canActivate: [authGuard] },
  { path: 'sign-in', component: SignIn, canActivate: [anonymousGuard] },
  { path: '**', redirectTo: '' },
];
