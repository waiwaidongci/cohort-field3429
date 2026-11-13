import {request} from './client';import type {Segment,Comparison} from '../types/domain';
export const getSegments=(run?:number)=>request<Segment[]>('/segments'+(run?'?run_id='+run:''));
export const getComparison=(runA:number,runB:number)=>request<Comparison>('/segments/compare?run_a='+runA+'&run_b='+runB);
