// Adapter around the pinned authors' generator; see upstream_generator.py.
#include <bits/stdc++.h>
static unsigned int task_seed;
class SeededDevice { public: unsigned int operator()() const { return task_seed; } };
struct pnt;
void capture_obstacle(const pnt&, const std::vector<pnt>&, int, int, bool);
#define random_device SeededDevice
#define main upstream_generator_main
#include "../build/upstream_generator_instrumented.inc"
#undef main
#undef random_device

struct RecordedObstacle { std::vector<std::array<int,3>> nodes; int step_ticks, extra_goal_tick; };
std::vector<RecordedObstacle> recorded;
void capture_obstacle(const pnt& finish,const std::vector<pnt>& visited,int delay,int speed,bool temporal) {
    RecordedObstacle record;
    record.step_ticks=speed*F;
    // Preserve the independent branch's extra unshifted goal reservation.
    record.extra_goal_tick=temporal?-1:finish.cost*F;
    auto node=finish;
    while(true) {
        record.nodes.push_back({node.x,node.y,(node.cost+(temporal?0:delay))*F});
        if(node.par_id==-1) break;
        node=visited[node.par_id];
    }
    std::reverse(record.nodes.begin(),record.nodes.end());
    recorded.push_back(std::move(record));
}
int main() {
    std::ios::sync_with_stdio(false);
    int count,sr,sc,gr,gc;
    if(!(std::cin>>H>>W>>MAP>>task_seed>>count>>sr>>sc>>gr>>gc)) return 2;
    if(H<1 || W<1 || H>MX_HEIGHT || W>MX_WIDTH || count<0) return 2;
    for(int r=0;r<H;++r) {
        std::string row;std::cin>>row;
        if(static_cast<int>(row.size())!=W)return 2;
        for(int c=0;c<W;++c)mp[r][c]=row[c]=='#';
    }
    mp[sr][sc]=mp[gr][gc]=true;
    generate_obstacles1(count);
    if(static_cast<int>(recorded.size())!=count)return 3;
    std::cout<<"{\"obstacles\":[";
    for(int i=0;i<count;++i) {
        if(i)std::cout<<',';
        auto& obstacle=recorded[i];
        std::cout<<"{\"id\":"<<i<<",\"base_step_ticks\":"<<obstacle.step_ticks<<",\"nodes\":[";
        for(size_t j=0;j<obstacle.nodes.size();++j) {
            if(j)std::cout<<',';
            auto node=obstacle.nodes[j];std::cout<<'['<<node[0]<<','<<node[1]<<','<<node[2]<<']';
        }
        auto goal=obstacle.nodes.back();
        std::cout<<"],\"goal\":["<<goal[0]<<','<<goal[1]<<"],\"extra_reservations\":[";
        if(obstacle.extra_goal_tick>=0)std::cout<<'['<<goal[0]<<','<<goal[1]<<','<<obstacle.extra_goal_tick<<','<<obstacle.extra_goal_tick<<']';
        std::cout<<"]}";
    }
    std::cout<<"],\"reservations\":[";
    bool comma=false;
    for(int r=0;r<H;++r)for(int c=0;c<W;++c)for(int t=0;t<MXT;++t)if(rsrv[r][c][t]) {
        int end=t;while(end+1<MXT&&rsrv[r][c][end+1])++end;
        if(comma)std::cout<<',';
        comma=true;
        std::cout<<'['<<r<<','<<c<<','<<t*F<<','<<end*F<<']';t=end;
    }
    std::cout<<"]}\n";
}
