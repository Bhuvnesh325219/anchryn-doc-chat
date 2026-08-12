import { HttpInterceptorFn } from '@angular/common/http';
import { inject } from '@angular/core';
import { Router } from '@angular/router';
import { catchError, throwError } from 'rxjs';

import { Auth } from './auth';

/**
 * Attaches the access token, and signs out when the server rejects it.
 *
 * Doing this centrally means no component can forget it, and an expired token
 * produces one clean redirect rather than a cascade of failed requests each
 * showing their own error.
 */
export const authInterceptor: HttpInterceptorFn = (request, next) => {
  const auth = inject(Auth);
  const router = inject(Router);
  const token = auth.token();

  const authorised = token
    ? request.clone({ setHeaders: { Authorization: `Bearer ${token}` } })
    : request;

  return next(authorised).pipe(
    catchError((error: unknown) => {
      const status = (error as { status?: number })?.status;
      // Only a 401 means the credentials are the problem. A 403 would be a
      // permission decision, and signing the user out over one would be wrong.
      if (status === 401 && auth.token()) {
        auth.clear();
        router.navigate(['/sign-in']);
      }
      return throwError(() => error);
    }),
  );
};
