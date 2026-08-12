import { inject } from '@angular/core';
import { CanActivateFn, Router } from '@angular/router';

import { Auth } from './auth';

/** Keeps the chat behind a sign-in. */
export const authGuard: CanActivateFn = () => {
  const auth = inject(Auth);
  const router = inject(Router);

  return auth.signedIn() ? true : router.createUrlTree(['/sign-in']);
};

/** Sends an already signed-in visitor away from the sign-in page. */
export const anonymousGuard: CanActivateFn = () => {
  const auth = inject(Auth);
  const router = inject(Router);

  return auth.signedIn() ? router.createUrlTree(['/']) : true;
};
