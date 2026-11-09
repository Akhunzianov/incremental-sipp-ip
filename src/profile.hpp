#pragma once
#ifdef SIPP_PHASE_PROFILE
#include "model.hpp"

namespace phase_profile {
enum Phase {lookup, projection, witness, ownership, queue, release, count};
inline std::array<double,count> totals{};
struct Scope {
    inline static Scope* active=nullptr;
    Scope* parent=active;
    Clock::time_point start=Clock::now();
    Phase phase;
    double nested=0;
    explicit Scope(Phase p):phase(p){active=this;}
    ~Scope(){
        double us=std::chrono::duration<double,std::micro>(Clock::now()-start).count();
        totals[phase]+=us-nested;
        if(parent)parent->nested+=us;
        active=parent;
    }
};
inline void emit(){
    const char* names[]={"lookup","projection","witness","ownership","queue","release"};
    std::cout<<"\"phases\":{";
    for(int i=0;i<count;++i)std::cout<<(i?",":"")<<'"'<<names[i]<<"\":"<<totals[i];
    std::cout<<"},";
}
}
#define PROFILE_PHASE(name) phase_profile::Scope measured_scope(phase_profile::name)
#define PROFILE_RESET() phase_profile::totals.fill(0)
#define PROFILE_EMIT() phase_profile::emit()
#else
#define PROFILE_PHASE(name)
#define PROFILE_RESET()
#define PROFILE_EMIT()
#endif
